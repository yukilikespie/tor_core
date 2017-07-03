import logging
import sys

import redis
from bugsnag.handlers import BugsnagHandler
from praw import Reddit

from tor_core.config import config
from tor_core.helpers import clean_list
from tor_core.helpers import get_wiki_page
from tor_core.helpers import log_header


def configure_tor(config):
    """
    Assembles the tor object based on whether or not we've enabled debug mode
    and returns it. There's really no reason to put together a Subreddit
    object dedicated to our subreddit -- it just makes some future lines
    a little easier to type.

    :param r: the active Reddit object.
    :param config: the global config object.
    :return: the Subreddit object for the chosen subreddit.
    """
    if config.debug_mode:
        tor = config.r.subreddit('ModsOfToR')
    else:
        # normal operation, our primary subreddit
        tor = config.r.subreddit('transcribersofreddit')

    return tor


def configure_redis():
    """
    Creates a connection to the local Redis server, then returns the active
    connection.

    :return: object: the active Redis object.
    """
    try:
        redis_server = redis.StrictRedis(host='localhost', port=6379, db=0)
        redis_server.ping()
    except redis.exceptions.ConnectionError:
        logging.fatal("Redis server is not running! Exiting!")
        sys.exit(1)

    return redis_server


def configure_logging(config, log_name='transcribersofreddit.log'):
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] - [%(levelname)s] - [%(funcName)s] - %(message)s',
        datefmt='%m/%d/%Y %I:%M:%S %p',
        filename=log_name
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] - [%(funcName)s] - %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)

    # add the handlers to the root logger
    logging.getLogger('').addHandler(console)
    # will intercept anything error level or above
    if config.bugsnag_api_key:
        bs_handler = BugsnagHandler()
        bs_handler.setLevel(logging.ERROR)
        logging.getLogger('').addHandler(bs_handler)

    if config.bugsnag_api_key:
        logging.info('Bugsnag enabled!')
    else:
        logging.info('Not running with Bugsnag!')

    log_header('Starting!')


def populate_header(config):
    config.header = ''
    config.header = get_wiki_page('format/header', config)


def populate_formatting(config):
    """
    Grabs the contents of the three wiki pages that contain the
    formatting examples and stores them in the config object.

    :return: None.
    """
    # zero out everything so we can reinitialize later
    config.audio_formatting = ''
    config.video_formatting = ''
    config.image_formatting = ''

    config.audio_formatting = get_wiki_page('format/audio', config)
    config.video_formatting = get_wiki_page('format/video', config)
    config.image_formatting = get_wiki_page('format/images', config)


def populate_domain_lists(config):
    """
    Loads the approved content domains into the config object from the
    wiki page.

    :return: None.
    """

    config.video_domains = []
    config.image_domains = []
    config.audio_domains = []

    domains = get_wiki_page('domains', config)
    domains = ''.join(domains.splitlines()).split('---')

    for domainset in domains:
        domain_list = domainset[domainset.index('['):].strip('[]').split(', ')
        current_domain_list = []
        if domainset.startswith('video'):
            current_domain_list = config.video_domains
        elif domainset.startswith('audio'):
            current_domain_list = config.audio_domains
        elif domainset.startswith('images'):
            current_domain_list = config.image_domains
        [current_domain_list.append(x) for x in domain_list]
        logging.debug('Domain list populated: {}'.format(current_domain_list))


def populate_moderators(config):
    # Praw doesn't cache this information, so it requests it every damn time
    # we ask about the moderators. Let's cache this so we can drastically cut
    # down on the number of calls for the mod list.

    # nuke the existing list
    config.tor_mods = []

    # this call returns a full list rather than a generator. Praw is weird.
    config.tor_mods = config.tor.moderator()


def populate_subreddit_lists(config):
    """
    Gets the list of subreddits to monitor and loads it into memory.

    :return: None.
    """

    config.subreddits_to_check = []
    config.upvote_filter_subs = {}
    config.no_link_header_subs = []

    config.subreddits_to_check = get_wiki_page('subreddits', config).split('\r\n')
    config.subreddits_to_check = clean_list(config.subreddits_to_check)
    logging.debug(
        'Created list of subreddits from wiki: {}'.format(
            config.subreddits_to_check
        )
    )

    for line in get_wiki_page(
        'subreddits/upvote-filtered', config
    ).splitlines():
        if ',' in line:
            sub, threshold = line.split(',')
            config.upvote_filter_subs[sub] = int(threshold)

    logging.debug(
        'Retrieved subreddits subject to the upvote filter: {}'.format(
            config.upvote_filter_subs
        )
    )

    config.no_link_header_subs = get_wiki_page(
        'subreddits/no-link-header', config
    ).split('\r\n')
    config.no_link_header_subs = clean_list(config.no_link_header_subs)
    logging.debug(
        'Retrieved subreddits subject to the upvote filter: {}'.format(
            config.no_link_header_subs
        )
    )

    lines = get_wiki_page('subreddits/archive-time', config).splitlines()
    config.archive_time_default = int(lines[0])
    config.archive_time_subreddits = {}
    for line in lines[1:]:
        if ',' in line:
            sub, time = line.split(',')
            config.archive_time_subreddits[sub.lower()] = int(time)


def populate_gifs(config):
    # zero it out so we can load more
    config.no_gifs = []
    config.no_gifs = get_wiki_page('usefulgifs/no', config).split('\r\n')


def initialize(config):
    populate_domain_lists(config)
    logging.debug('Domains loaded.')
    populate_subreddit_lists(config)
    logging.debug('Subreddits loaded.')
    populate_formatting(config)
    logging.debug('Formatting loaded.')
    populate_header(config)
    logging.debug('Header loaded.')
    populate_moderators(config)
    logging.debug('Mod list loaded.')
    populate_gifs(config)
    logging.debug('Gifs loaded.')


def build_bot(name, log_name='transcribersofreddit.log', require_redis=True):
    """
    Shortcut for setting up a bot instance. Runs all configuration and returns
    a valid config object.

    :param name: The name of the bot to be started; this name must match the
        settings in praw.ini
    :return: a generated config object
    """

    config.r = Reddit(name)
    configure_logging(config, log_name=log_name)

    if require_redis:
        config.redis = configure_redis()
    else:
        # I'm sorry
        config.redis = lambda: (_ for _ in ()).throw(NotImplementedError('Redis was disabled during building!'))

    config.tor = configure_tor(config)
    initialize(config)
    logging.info('Bot built and initialized!')
    return config