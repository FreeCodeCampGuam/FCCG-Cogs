# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord

import os
import os.path
import aiohttp
import asyncio
import discord
from datetime import datetime, timedelta
from copy import copy
from discord.ext import commands
from cogs.utils.dataIO import dataIO


class GitHub:
    """Accesses GitHub."""

    def __init__(self, bot):
        self.bot = bot
        self.settingPath = "data/github/settings.json"
        self.settings = dataIO.load_json(self.settingPath)
        # async functions can't be called without being in another async function
        # so _log_in and _wait_for_issue are added to the bot's event loop
        self.bot.loop.create_task(self._update_server_list())
        self.bot.loop.create_task(self._log_in())
        self.bot.loop.create_task(self._wait_for_updates())

    def _format_issue(self, issue, repo):
        """Formats a GitHub issue nicely so it can be printed in Discord. issue is the dict returned by a GitHub
        API request for a given Issue."""
        string = "New issue on `{}` by {}: **{}**\n{}"
        fullstring = string.format(repo, issue["user"]["login"], issue["title"], issue["html_url"])
        return fullstring

    async def _update_server_list(self):
        """Ensures config file has all servers loaded on startup."""
        for server in self.bot.servers:
            if server.id not in self.settings["servers"].keys():
                print("Added {} to server list.".format(server.name))
                info = {"repos": [],
                        "notification_method": tuple(),
                        "interval": 3600
                        }
                self.settings["servers"][server.id] = info
                dataIO.save_json(self.settingPath, self.settings)

    async def _log_in(self):
        """Attempts to log in to GitHub through the API with the given
        credentials."""
        # tries to use what's in the settings
        usr = self.settings["github_username"]
        token = self.settings["personal_access_token"]
        # but if hasn't been validated yet, ask for credentials anyway
        # through console/terminal
        if self.settings["validated"] is not True:
            print("Please enter GitHub username.")
            usr = input()
            self.settings["github_username"] = usr
            print("Please enter GitHub Personal Access Token.")
            token = input()
            self.settings["personal_access_token"] = token
        try:
            # basic authentication request
            r = await aiohttp.request("GET","https://api.github.com/user",auth=aiohttp.BasicAuth(usr,token))
        except Exception as e:
            # if exception happened during authentication request, assume validation failed
            print("GitHub login as {} failed.".format(usr))
            print("{}: {}".format(e.__name__, e))
            self.settings["validated"] = False
        else:
            if r.status == 200:  # OK
                print("Login succeeded as {}!".format(usr))
                # setting validated to True bypasses asking for credentials on
                # cog startup
                self.settings["validated"] = True
            else:
                self.settings["validated"] = False
        # always save
        dataIO.save_json(self.settingPath, self.settings)

    async def _create_digest(self, server):
        """Grabs the most recent happenings for each repo, prints nicely."""
        # all updates since "last update"
        # subtracting these datetime objects should give current time "minus" the interval
        # that is, the time interval seconds ago
        seconds = self.settings["servers"][server.id]["interval"]
        d = datetime.utcnow() - timedelta(seconds=seconds)
        # GitHub API takes ISO 8601 format for dates/times
        # so we need just a little bit more formatting
        datestring = d.isoformat()[:-7] + "Z"
        # setting the 'since' parameter in a request for issues
        # only retrieves issues after a certain time
        parameters = {"since": datestring}
        for repo in self.settings["servers"][server.id]["repos"]:
            print("Checking repo {}...".format(repo))
            site = "https://api.github.com/repos/{}/issues".format(repo)
            async with aiohttp.get(site.format(repo), params=parameters) as response:
                status = response.status
                reason = response.reason
                data = await response.json()
            # display response code and reason, for debugging
            # ret = "```{}: {}```".format(status, reason)
            # await self.bot.send_message(ret, channel)
            if status == 200:
                if self.settings["servers"][server.id]["notification_method"][0] == "message":
                    channelId = self.settings["servers"][server.id]["notification_method"][1]
                    dest = self.bot.get_channel(channelId)
                    for issue in data:
                        await self.bot.send_message(self._format_issue(issue, repo), dest)
                elif self.settings["notification_method"][0] == "webhook":
                    await self._fire_hooks(server)

    async def _wait_for_updates(self):
        """Checks for updates from assigned GitHub repos at given interval."""
        await self.bot.wait_until_ready()
        # loops until bot stops functioning
        referenceCount = 0
        while not self.bot.is_closed:
            for server in self.bot.servers:
                # checks if current second count since startup is evenly
                # divisible by each server's set interval, effectively firing
                # digests at each server's interval
                intrval = self.settings["servers"][server.id]["interval"]
                if referenceCount % intrval == 0:
                    # notification when scheduled digests fire
                    print("Scheduled digests firing!")
                    await self._create_digest(server)
            await asyncio.sleep(1)
            referenceCount += 1

    @commands.group(pass_context=True, name="notifymethod")
    async def _set_notification_method(self, ctx):
        """Changes whether digests are created using normal messages
        or using webhooks."""

    @_set_notification_method.command(pass_context=True)
    async def message(self, ctx, channel_name: str):
        """Changes cog to send digests to specified channel."""
        # check if channel is on server where command is given
        print([c.name for c in ctx.message.server.channels])
        for channel in ctx.message.server.channels:
            if channel.name == channel_name:
                print("Match!")
                channelId = channel.id
                break
                print("break fail")
        else:
            msg = "Channel `{}` not found on this server!".format(channel_name)
            await self.bot.say(msg)
            return
        serverId = ctx.message.server.id
        st = ("message", channelId)
        self.settings["servers"][serverId]["notification_method"] = st
        dataIO.save_json(self.settingPath, self.settings)
        msg = "Set notification method to message #{}".format(channel)
        await self.bot.say(msg)

    @_set_notification_method.command(pass_context=True)
    async def webhook(self, ctx, hook_url: str):
        """Changes cog to send digests utilizing specified webhook."""
        beginUrl = "https://canary.discordapp.com/api/webhooks/"
        # pull webhook id from URL
        if hook_url.startswith(beginUrl):
            hookId = hook_url.split("/")[5]
        async with aiohttp.get(beginUrl + hookId) as response:
            status = response.status
            reason = response.reason
        if status == 200:  # OK
            await self.bot.say("Webhook validated.")
            serverId = ctx.message.server.id
            st = ("webhook", hook_url)
            self.settings["servers"][serverId]["notification_methods"] = st
            dataIO.save_json(self.settingPath, self.settings)
        else:
            script = "Webhook validation failed: {}: {}".format(status, reason)
            await self.bot.say(script)

    @commands.command(name="gitupdate", pass_context=True)
    async def _force_grab_updates(self, ctx):
        """Produces a digest on command."""
        await self._create_digest(ctx.message.server)

    @commands.command(pass_context=True, name="setin")
    async def _set_interval(self, ctx, interval: int):
        """Sets the interval at which the cog checks for updates in minutes."""
        # minimum digest interval is 60 minutes, subject to change
        if interval < 60:
            interval = 60
        interval *= 60  # in minutes
        self.settings["servers"][ctx.message.server.id]["interval"] = interval
        await self.bot.say("Check delay set to {} minutes.".format(interval))
        dataIO.save_json(self.settingPath, self.settings)

    @commands.command(pass_context=True, name="addrepo")
    async def _add_repo(self, ctx, repostr: str):
        """Adds a repository to the set of repos to be checked regularly.
        First checks if it is a valid/accessible repo."""
        if "/" in repostr:
            owner, repo = repostr.split("/")
        site = "https://api.github.com/repos/{}/{}".format(owner, repo)
        async with aiohttp.get(site) as response:
            status = response.status
        # if retrieval was success, assume repo is valid
        if status == 200:  # OK
            msg = "Repository verified. Adding to list of sources."
            await self.bot.say(msg)
            serverId = ctx.message.server.id
            self.settings["servers"][serverId]["repos"].append(repostr)
            dataIO.save_json(self.settingPath, self.settings)
        # if repo nonexistent, say so
        elif status == 404:  # Not Found
            await self.bot.say("Repository not found.")
        # for anything else that might happen
        else:
            msg = "An unkown error occurred. Repository not verified."
            await self.bot.say(msg)

    @commands.command(pass_context=True, name="lsrepo")
    async def _list_repos(self, ctx):
        """Lists currently added repos."""
        # turns list of repos into GitHub links
        repos = self.settings["servers"][ctx.message.server.id]["repos"]
        r = "\n".join(["https://github.com/{}".format(s) for s in repos])
        await self.bot.say("```Currently added repositories:\n{}```".format(r))

    @commands.command(pass_context=True, name="delrepo")
    async def _delete_repo(self, repostr: str):
        """Removes repository from set of repos to be checked regularly."""
        repos = self.settings["repos"]
        # since you shouldn't delete a value in something you're iterating over
        # searches through added repos for a match, and binds it with `r`
        # then breaks from the loop
        toPop = None
        for r in repos:
            if repostr == r:
                toPop = r
                break
        # if r hasn't been marked, the repo hasn't been added
        if toPop is None:
            await self.bot.reply("Repository not found!")
        else:
            await self.bot.say("Removing repo `{}` from list.".format(repostr))
            self.settings["servers"][ctx.message.server.id]["repos"].pop(r)
            dataIO.save_json(self.settingPath, self.settings)


def check_folder():
    if not os.path.exists("data/github"):
        print("data/github not detected, creating folder...")
        os.makedirs("data/github")


def check_file():
    defaultSettings = {"interval": 60,
                       "github_username": "",
                       "validated": None,
                       "personal_access_token": "",
                       "servers": {}
                       }
    s = "data/github/settings.json"
    if not dataIO.is_valid_json(s):
        print("valid github/settings.json not detected, creating...")
        dataIO.save_json(s, defaultSettings)


def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(GitHub(bot))
