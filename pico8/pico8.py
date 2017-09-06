import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
from bs4 import BeautifulSoup
import asyncio
import os
import aiohttp
import re
from random import randint
from random import choice as randchoice
from __main__ import send_cmd_help

SETTINGS_PATH = "data/pico8/settings.json"


class BBS:
    """BBS Api Wrapper"""
    BASE = "https://www.lexaloffle.com/bbs/"
    PARAMS = {
        "cat": {
            "VOXATRON":      "6",
            "PICO8":         "7",
            "BLOGS":         "8"
        },
        "sub": {
            "DISCUSSIONS":   "1",
            "CARTRIDGES":    "2",
            "WIP":           "3",
            "COLLABORATION": "4",
            "WORKSHOPS":     "5",
            "SUPPORT":       "6",
            "BLOGS":         "7",
            "JAMS":          "8",
            "SNIPPETS":      "9",
            "PIXELS":        "10",
            "ART":           "10",
            "MUSIC":         "11"
        },
        "orderby": {
            "RECENT":        "ts",
            "FEATURED":      "rating",  
            "RATING":        "rating",
            "FAVORITES":     "favourites",
            "FAVOURITES":    "favourites"
        }
    }

    def __init__(self, loop, search, orderby="RECENT", params={}):
        self.url = BBS.BASE
        self.search_term = search
        self.loop = loop
        self.orderby = orderby
        self.params = {}
        for p, v in self.params.items():
            self.set_param(p, v)
        self.posts = []
        self.current_post = 0
        self.queue = []

    async def __aenter__(self):
        self.runner = self.loop.create_task(self._queue_runner())
        await self.search(self.search_term, self.orderby)
        return self

    async def __aexit__(self, *args):
        self.runner.cancel()

    def set_search(self, term):
        self.params.update({'search': term})

    async def search(self, term, orderby="RECENT"):
        self.set_search(term)
        self.set_param("orderby", orderby)
        await self._populate_results()

        return self.posts

    async def _populate_results(self):
        raw = await self._get()
        soup = BeautifulSoup(raw, "html.parser")
        posts = soup.find_all(id=re.compile("pdat_.*"))
        self.posts = [{"TITLE": t.a.text,
                       "STATUS": "",
                       "PARAM": {"tid": t.a['href'][5:]}} for t in posts]
        await self._populate_post(0)
        self.queue = [0,-1,1]

    async def _populate_post(self, index_or_id, post=None):
        # hope this doesn't fail
        post = post or self.posts[self._get_post_index(index_or_id)]
        post['STATUS'] = 'processing'
        try:
            index = self._get_post_index(index_or_id)
            raw = await self._get_post(index)
            soup = BeautifulSoup(raw, "html.parser")
            # continue
            post['SOUP'] = soup
        except Exception as e:
            post['STATUS'] = 'failed'
            raise e
        post['STATUS'] = 'success'


    def _get_post_index(self, index_or_id):
        try:
            self.posts[index_or_id]
        except TypeError:
            for n, p in enumerate(self.posts):
                if p["PARAM"]['tid'] == index_or_id:
                    return n
        else:
            return index_or_id
        raise KeyError('index does not exist in posts')

    async def _get_post(self, index_or_id):
        index = self._get_post_index(index_or_id)
        post = self.posts[index]
        param = post["PARAM"]
        return await self._get(param)

    async def _get(self, params=None):
        params = params or self.params
        async with aiohttp.get(self.url, params=params) as r:
            return await r.text()

    async def _queue_runner(self):
        while True:
            if self.queue:
                working_group = []
                for i in self.queue[:]:
                    status = self.posts[i]["STATUS"]
                    if status == 'success':
                        self.queue.remove(i)
                    if status in ('', 'failed'):
                        working_group.append(i)
                for i in working_group:
                    self.loop.create_task(self._populate_post(i))
            await asyncio.sleep(.5) 



    def set_param(self, param, value_name):
        self.params[param] = self.get_value(param, value_name)

    def set_param_by_prefix(self, param, prefix):
        value_name = self.get_value_name_by_prefix(param, prefix)
        return self.add_param(param, value_name)

    def param_exists(self, param):
        return param in BBS.PARAMS

    def value_name_exists(self, param, value_name):
        return self.param_exists(param) and value_name in BBS.PARAMS[param]

    def get_value(self, param, value_name):
        return BBS.PARAMS[param][value_name]

    def get_value_by_prefix(self, param, prefix):
        value_name = self.get_value_name_by_prefix(param, prefix)
        return self.get_value(param, value_name)

    def get_value_name_by_prefix(self, param, prefix):
        group = BBS.PARAMS[param]
        upper_no_s = prefix.upper()[-1]

        for name in group:
            if name.startswith(upper_no_s):
                return name

        raise ValueError('Prefix {} not found in param {}'
                         .format(prefix, param))

    def add_to_queue(self, post):
        if post in self.queue:
            return False
        self.queue.append(post)

# [{'href':t.a['href'], 'text':t.a.text}  for t in s.find_all(id=re.compile("pdat_.*"))]

"""
UI Ideas:

Cart: 
    png for thumbnail
    in code:
        -- cart name
        -- by author

Other:
    link
    author thumbnail somewhere
    author name
    title
    description[:n_chars] + '...'
    stars
    hearts
    CC?
    tags
    date


Card:
    [Title](link to post)    author.avatar
    Description

    Cart Name           Tags:
    by author           tags, tags, tags

    Cart thumbnail (or png cart?) or default "no cart" logo

    footer: date, CC, hearts, starts

    controls:
    < x >

"""


class Pico8:
    """cog to search Lexaloffle's BBS and notify when new PICO-8 carts are uploaded"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @commands.group(pass_context=True, no_pm=True, aliases=['pico8'])
    async def bbs(self, ctx):
        """PICO-8 bbs commands"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @bbs.command(pass_context=True, name="search", no_pm=True)
    async def bbs_search(self, ctx, category="Recent", search_terms=""):
        """Search PICO-8's bbs in a certain category

        Categories (default Recent):
            Recent       Discussion   Blogs
            Carts        Collab       Workshop
            Support      Jam          WIP
            Snippets     Art          Music

        leave search_term blank to list newest topics
        in the category
        """
def check_folders():
    paths = ("data/pico8", )
    for path in paths:
        if not os.path.exists(path):
            print("Creating {} folder...".format(path))
            os.makedirs(path)


def check_files():
    default = {}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default pico8 settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print("Adding " + str(key) +
                          " field to pico8 settings.json")
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot):
    check_folders()
    check_files()
    n = Pico8(bot)
    bot.add_cog(n)