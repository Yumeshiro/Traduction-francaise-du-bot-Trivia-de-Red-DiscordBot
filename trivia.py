from discord.ext import commands
from random import choice
from .utils.dataIO import dataIO
from .utils import checks
from .utils.chat_formatting import box
from collections import Counter, defaultdict, namedtuple
import discord
import time
import os
import asyncio
import chardet

DEFAULTS = {"MAX_SCORE"    : 10,
            "TIMEOUT"      : 120,
            "DELAY"        : 20,
            "BOT_PLAYS"    : False,
            "REVEAL_ANSWER": True}

TriviaLine = namedtuple("TriviaLine", "question answers")


class Trivia:
    """General commands."""
    def __init__(self, bot):
        self.bot = bot
        self.trivia_sessions = []
        self.file_path = "data/trivia/settings.json"
        settings = dataIO.load_json(self.file_path)
        self.settings = defaultdict(lambda: DEFAULTS.copy(), settings)

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(administrator=True)
    async def triviaset(self, ctx):
        """Change trivia settings"""
        server = ctx.message.server
        if ctx.invoked_subcommand is None:
            settings = self.settings[server.id]
            msg = box("Le rouge gagne des points: {BOT_PLAYS}\n"
                      "Secondes pour repondre: {DELAY}\n"
                      "Points a gagner: {MAX_SCORE}\n"
                      "Revelez la reponse a l'expiration: {REVEAL_ANSWER}\n"
                      "".format(**settings))
            msg += "\nSee {}help triviaset to edit the settings".format(ctx.prefix)
            await self.bot.say(msg)

    @triviaset.command(pass_context=True)
    async def maxscore(self, ctx, score : int):
        """Points required to win"""
        server = ctx.message.server
        if score > 0:
            self.settings[server.id]["MAX_SCORE"] = score
            self.save_settings()
            await self.bot.say("Points requis pour gagner {}".format(score))
        else:
            await self.bot.say("Le score doit etre superieur a 0.")

    @triviaset.command(pass_context=True)
    async def timelimit(self, ctx, seconds : int):
        """Maximum Secondes pour repondre"""
        server = ctx.message.server
        if seconds > 4:
            self.settings[server.id]["DELAY"] = seconds
            self.save_settings()
            await self.bot.say("Maximum Secondes pour repondre set to {}".format(seconds))
        else:
            await self.bot.say("Les secondes doivent etre au moins 5.")

    @triviaset.command(pass_context=True)
    async def botplays(self, ctx):
        """Le rouge gagne des points"""
        server = ctx.message.server
        if self.settings[server.id]["BOT_PLAYS"]:
            self.settings[server.id]["BOT_PLAYS"] = False
            await self.bot.say("D'accord, je ne vous embarasserai plus pour des anecdotes.")
        else:
            self.settings[server.id]["BOT_PLAYS"] = True
            await self.bot.say("Je vais gagner un point chaque fois que tu ne reponds pas a temps.")
        self.save_settings()

    @triviaset.command(pass_context=True)
    async def revealanswer(self, ctx):
        """Revele la reponse a la question sur le timeout"""
        server = ctx.message.server
        if self.settings[server.id]["REVEAL_ANSWER"]:
            self.settings[server.id]["REVEAL_ANSWER"] = False
            await self.bot.say("Je ne revelerai plus la reponse aux questions.") 
        else:
            self.settings[server.id]["REVEAL_ANSWER"] = True
            await self.bot.say("Je vais reveler la reponse si personne ne le sait.")
        self.save_settings()

    @commands.group(pass_context=True, invoke_without_command=True, no_pm=True)
    async def trivia(self, ctx, list_name: str):
        """Start a trivia session with the specified list"""
        message = ctx.message
        server = message.server
        session = self.get_trivia_by_channel(message.channel)
        if not session:
            try:
                trivia_list = self.parse_trivia_list(list_name)
            except FileNotFoundError:
                await self.bot.say("Cette liste de trivia n'existe pas.")
            except Exception as e:
                print(e)
                await self.bot.say("Erreur lors du chargement de la liste.")
            else:
                settings = self.settings[server.id]
                t = TriviaSession(self.bot, trivia_list, message, settings)
                self.trivia_sessions.append(t)
                await t.new_question()
        else:
            await self.bot.say("Une liste de questions est deja en cours dans ce channel.")

    @trivia.group(name="stop", pass_context=True, no_pm=True)
    async def trivia_stop(self, ctx):
        """Arrete une session de questions en cours"""
        author = ctx.message.author
        server = author.server
        admin_role = self.bot.settings.get_server_admin(server)
        mod_role = self.bot.settings.get_server_mod(server)
        is_admin = discord.utils.get(author.roles, name=admin_role)
        is_mod = discord.utils.get(author.roles, name=mod_role)
        is_owner = author.id == self.bot.settings.owner
        is_server_owner = author == server.owner
        is_authorized = is_admin or is_mod or is_owner or is_server_owner

        session = self.get_trivia_by_channel(ctx.message.channel)
        if session:
            if author == session.starter or is_authorized:
                await session.end_game()
                await self.bot.say("Trivia arrette.")
            else:
                await self.bot.say("Vous n'etes pas autorise a le faire.")
        else:
            await self.bot.say("Il n'y a pas de session de questions en cours sur ce canal.")

    @trivia.group(name="list")
    async def trivia_list(self):
        """Shows available trivia lists"""
        lists = os.listdir("data/trivia/")
        lists = [l for l in lists if l.endswith(".txt") and " " not in l]
        lists = [l.replace(".txt", "") for l in lists]

        if lists:
            msg = "+ Available trivia lists\n\n" + ", ".join(sorted(lists))
            msg = box(msg, lang="diff")
            if len(lists) < 100:
                await self.bot.say(msg)
            else:
                await self.bot.whisper(msg)
        else:
            await self.bot.say("Il n'y a pas de listes de questions disponibles.")

    def parse_trivia_list(self, filename):
        path = "data/trivia/{}.txt".format(filename)
        parsed_list = []

        with open(path, "rb") as f:
            try:
                encoding = chardet.detect(f.read())["encoding"]
            except:
                encoding = "ISO-8859-1"

        with open(path, "r", encoding=encoding) as f:
            trivia_list = f.readlines()

        for line in trivia_list:
            if "`" not in line:
                continue
            line = line.replace("\n", "")
            line = line.split("`")
            question = line[0]
            answers = []
            for l in line[1:]:
                answers.append(l.strip())
            if len(line) >= 2 and question and answers:
                line = TriviaLine(question=question, answers=answers)
                parsed_list.append(line)

        if not parsed_list:
            raise ValueError("Empty trivia list")

        return parsed_list

    def get_trivia_by_channel(self, channel):
        for t in self.trivia_sessions:
            if t.channel == channel:
                return t
        return None

    async def on_message(self, message):
        if message.author != self.bot.user:
            session = self.get_trivia_by_channel(message.channel)
            if session:
                await session.check_answer(message)

    async def on_trivia_end(self, instance):
        if instance in self.trivia_sessions:
            self.trivia_sessions.remove(instance)

    def save_settings(self):
        dataIO.save_json(self.file_path, self.settings)


class TriviaSession():
    def __init__(self, bot, trivia_list, message, settings):
        self.bot = bot
        self.reveal_messages = ("Je connais celui-la! {}!",
                                "Facile: {}.",
                                "Oh vraiment, c'est {} bien sur.")
        self.fail_messages = ("Au prochain je suppose...",
                              "En route...",
                              "Je suis sur que vous connaitrez la prochaine.",
                              "\N{PENSIVE FACE} Le prochain.")
        self.current_line = None # {"QUESTION" : "String", "ANSWERS" : []}
        self.question_list = trivia_list
        self.channel = message.channel
        self.starter = message.author
        self.scores = Counter()
        self.status = "nouvelle question"
        self.timer = None
        self.timeout = time.perf_counter()
        self.count = 0
        self.settings = settings

    async def stop_trivia(self):
        self.status = "stop"
        self.bot.dispatch("trivia_end", self)

    async def end_game(self):
        self.status = "stop"
        if self.scores:
            await self.send_table()
        self.bot.dispatch("trivia_end", self)

    async def new_question(self):
        for score in self.scores.values():
            if score == self.settings["MAX_SCORE"]:
                await self.end_game()
                return True
        if self.question_list == []:
            await self.end_game()
            return True
        self.current_line = choice(self.question_list)
        self.question_list.remove(self.current_line)
        self.status = "waiting for answer"
        self.count += 1
        self.timer = int(time.perf_counter())
        msg = "**Question numero {}!**\n\n{}".format(self.count, self.current_line.question)
        await self.bot.say(msg)

        while self.status != "reponse correcte" and abs(self.timer - int(time.perf_counter())) <= self.settings["DELAY"]:
            if abs(self.timeout - int(time.perf_counter())) >= self.settings["TIMEOUT"]:
                await self.bot.say("Les gars ... Eh bien, je suppose que je m'arreterai alors.")
                await self.stop_trivia()
                return True
            await asyncio.sleep(1) #Waiting for an answer or for the time limit
        if self.status == "reponse correcte":
            self.status = "nouvelle question"
            await asyncio.sleep(3)
            if not self.status == "stop":
                await self.new_question()
        elif self.status == "stop":
            return True
        else:
            if self.settings["REVEAL_ANSWER"]:
                msg = choice(self.reveal_messages).format(self.current_line.answers[0])
            else:
                msg = choice(self.fail_messages)
            if self.settings["BOT_PLAYS"]:
                msg += " **+1** for me!"
                self.scores[self.bot.user] += 1
            self.current_line = None
            await self.bot.say(msg)
            await self.bot.type()
            await asyncio.sleep(3)
            if not self.status == "stop":
                await self.new_question()

    async def send_table(self):
        t = "+ Results: \n\n"
        for user, score in self.scores.most_common():
            t += "+ {}\t{}\n".format(user, score)
        await self.bot.say(box(t, lang="diff"))

    async def check_answer(self, message):
        if message.author == self.bot.user:
            return
        elif self.current_line is None:
            return

        self.timeout = time.perf_counter()
        has_guessed = False

        for answer in self.current_line.answers:
            answer = answer.lower()
            guess = message.content.lower()
            if " " not in answer:  # Exact matching, issue #331
                guess = guess.split(" ")
                for word in guess:
                    if word == answer:
                        has_guessed = True
            else:  # The answer has spaces, we can't be as strict
                if answer in guess:
                    has_guessed = True

        if has_guessed:
            self.current_line = None
            self.status = "reponse correcte"
            self.scores[message.author] += 1
            msg = "tu la eu {}! **+1** a toi!".format(message.author.name)
            await self.bot.send_message(message.channel, msg)


def check_folders():
    folders = ("data", "data/trivia/")
    for folder in folders:
        if not os.path.exists(folder):
            print("Creating " + folder + " folder...")
            os.makedirs(folder)


def check_files():
    if not os.path.isfile("data/trivia/settings.json"):
        print("Creating empty settings.json...")
        dataIO.save_json("data/trivia/settings.json", {})


def setup(bot):
    check_folders()
    check_files()
    bot.add_cog(Trivia(bot))
