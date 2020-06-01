#!/bin/env python

import logging
import os
import random
from collections import defaultdict, namedtuple

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import BaseFilter, CommandHandler, Filters, MessageHandler, Updater
from telegram.utils.helpers import mention_html

from config import TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


class FilterDart(BaseFilter):
    def filter(self, message):
        return message.dice.emoji == "🎯"


def get_score(value):
    return {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 6}.get(value)


PlayerState = namedtuple("PlayerState", ["score", "throws"])


def format_name(user):
    return user.first_name + ((" " + user.last_name) if user.last_name else "")


custom_keyboard = ReplyKeyboardMarkup([["🎯"]])


class ChatGame:
    def __init__(self, updater, update, ctx):
        self.updater = updater
        self.jq = updater.job_queue
        self.chat_id = update.effective_chat.id
        ctx.bot.send_message(
            chat_id=self.chat_id, text="k", reply_markup=custom_keyboard
        )
        self.states = defaultdict(lambda: PlayerState(0, 0))
        print("Starting game in chat {}".format(self.chat_id))
        self.replyjobs = dict()
        self.replystats = defaultdict(list)
        self.namecache = dict()
        self.dead = False

    def stop(self, update, ctx):
        textlines = [
            "{}: {} ({} throws) ({:.4f} average)".format(
                mention_html(i, self.namecache[i]),
                state.score,
                state.throws,
                state.score / state.throws,
            )
            for i, state in sorted(
                self.states.items(), key=lambda item: item[1].score, reverse=True
            )
        ]
        ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            parse_mode="HTML",
            text="\n".join(textlines),
            reply_markup=ReplyKeyboardRemove(),
        )
        self.states = None
        self.dead = True

    def dart(self, update, ctx):
        dice = update.message.dice
        user = update.message.from_user
        self.namecache[user.id] = format_name(user)
        old = self.states[user.id]
        delta = get_score(dice.value)
        state = PlayerState(old.score + delta, old.throws + 1)
        self.states[user.id] = state

        self.replystats[user.id].append(delta)
        cnt = len(self.replystats[user.id])

        rj = self.replyjobs.get(user.id, None)

        if rj:
            # XXX maybe race condition?
            rj.schedule_removal()

        def reply(ctx):
            newthrows = self.replystats[user.id][:cnt]

            if len(newthrows) > 100:
                s = "Not showing individual scores."
            else:
                s = " ".join((f"+{score}" for score in newthrows))
            update.message.reply_text(
                "{}\nThrows: {} (+{})\nScore: {} (+{})".format(
                    s, state.throws, cnt, state.score, sum(newthrows),
                )
            )
            self.replyjobs[user.id] = None
            self.replystats[user.id] = self.replystats[user.id][cnt:]

        self.replyjobs[user.id] = self.jq.run_once(reply, 2.5)


class DartboiBot:
    def __init__(self):
        self.updater = Updater(token=TOKEN, use_context=True)
        self.dp = self.updater.dispatcher

        handlers = [
            CommandHandler("start", self.start_command),
            CommandHandler("stop", self.meta_handler(ChatGame.stop)),
            MessageHandler(
                Filters.dice & FilterDart() & (~Filters.forwarded),
                self.meta_handler(ChatGame.dart),
            ),
        ]

        for h in handlers:
            self.dp.add_handler(h)

        self.games = dict()

    def run(self):
        self.updater.start_polling()
        self.updater.idle()

    def start_command(self, update, ctx):
        chatid = update.effective_chat.id
        if chatid in self.games:
            update.message.reply_text(random.choice(("あほか？", "ばか！")))
            return
        game = ChatGame(self.updater, update, ctx)
        self.games[chatid] = game

    def meta_handler(self, func):
        def inner(update, ctx):
            chat_id = update.effective_chat.id
            game = self.games.get(chat_id, None)
            if game is not None:
                func(game, update, ctx)
                if game.dead:
                    del self.games[chat_id]

        return inner


if __name__ == "__main__":
    DartboiBot().run()
