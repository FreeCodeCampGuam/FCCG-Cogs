import discord
from discord.ext import commands

from cogs.utils import checks
from __main__ import set_cog, send_cmd_help, settings

import subprocess

class wifiPresence:
    """My custom cog that does stuff!"""

    def __init__(self, bot):
        self.bot = bot
        self.scan_status = False

    def scan_arp(self, ctx):
        self.output = subprocess.check_output("sudo arp-scan -l", shell=True)
        return

    @commands.group(name = "presence", pass_context = True)
    async def presence(self,ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @commands.group(name = "scan", pass_context = True)
    async def scan(self,ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @scan.command(pass_context = True)
    async def toggle(self, ctx):
        """Toggles scan on or off"""
        self.scan_status = not self.scan_status
        if self.scan_status:
            await self.bot.say("Scanning Started.")
            while self.scan_status:
                await scan_arp()
                await asyncio.sleep(30)
        else:
            await self.bot.say("Scanning Stopped.")

    @checks.is_owner()
    @scan.command(pass_context = True)
    async def log(self,ctx):
        """Prints out a log of connected devices"""
        await scan_arp()
        readable_output = self.output.decode("utf-8")
        await self.bot.whisper("```" + readable_output + "```")
        await self.bot.say("Sent you a PM")
        

def setup(bot):
    bot.add_cog(wifiPresence(bot))