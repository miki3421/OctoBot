#  Drakkar-Software OctoBot-Interfaces
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.
import time
import flask
from octobot.ai_strategy_lab import btc_intraday_pair_view
from octobot.ai_strategy_lab import v13_m1_review_view
import json
import gzip
import pathlib
import sqlite3

import octobot_commons.authentication as authentication
import octobot_services.interfaces.util as interfaces_util
import tentacles.Services.Interfaces.web_interface.login as login
import tentacles.Services.Interfaces.web_interface.models as models
import tentacles.Services.Interfaces.web_interface.flask_util as flask_util
import tentacles.Services.Interfaces.web_interface.constants as web_constants
import octobot.constants as constants
import octobot_commons.constants
import octobot_commons.enums


def register(blueprint):
    @blueprint.route("/v13_variants/m1/review")
    @login.login_required_when_activated
    def v13_m1_review():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        response = flask.make_response(flask.render_template("v13_m1_review.html"))
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_variants/m1/review/data")
    @login.login_required_when_activated
    def v13_m1_review_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        response = flask.jsonify(v13_m1_review_view.public_view())
        response.cache_control.no_store = True
        return response

    @blueprint.route("/btc_intraday_pair")
    @login.login_required_when_activated
    def btc_intraday_pair_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        response = flask.make_response(flask.render_template("btc_intraday_pair.html"))
        response.cache_control.no_store = True
        return response

    @blueprint.route("/btc_intraday_pair/data")
    @login.login_required_when_activated
    def btc_intraday_pair_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            response = flask.jsonify(btc_intraday_pair_view.public())
        except (OSError, ValueError, KeyError, TypeError):
            response = flask.jsonify(dict(available=False, message="Confronto intraday non disponibile o non verificabile."))
            response.status_code = 503
        response.cache_control.no_store = True
        return response

    @blueprint.route("/")
    @blueprint.route("/home")
    @login.login_required_when_activated
    def home():
        if flask.request.args.get("reset_tutorials", "False") == "True":
            flask_util.BrowsingDataProvider.instance().set_first_displays(True)
        if models.accepted_terms():
            trading_delay_info = flask.request.args.get("trading_delay_info", 'false').lower() == "true"
            in_backtesting = models.get_in_backtesting_mode()
            display_intro = flask_util.BrowsingDataProvider.instance().get_and_unset_is_first_display(
                flask_util.BrowsingDataProvider.HOME
            )
            form_to_display = constants.WELCOME_FEEDBACK_FORM_ID
            pnl_symbols = models.get_pnl_history_symbols()
            all_time_frames = models.get_all_watched_time_frames()
            research_time_frame = octobot_commons.enums.TimeFrames.FIVE_MINUTES
            if research_time_frame not in all_time_frames:
                all_time_frames.insert(0, research_time_frame)
            display_time_frame = models.get_display_timeframe()
            display_orders = models.get_display_orders()
            sandbox_exchanges = models.get_sandbox_exchanges()
            try:
                user_id = models.get_user_account_id()
                display_feedback_form = form_to_display and not models.has_filled_form(form_to_display)
            except authentication.AuthenticationRequired:
                # no authenticated user: don't display form
                user_id = None
                display_feedback_form = False
            past_launch_time = (
                web_constants.PRODUCT_HUNT_ANNOUNCEMENT_DAY
                + (
                        octobot_commons.enums.TimeFramesMinutes[octobot_commons.enums.TimeFrames.ONE_DAY]
                        * octobot_commons.constants.MINUTE_TO_SECONDS
                )
            )
            is_launching = (
               web_constants.PRODUCT_HUNT_ANNOUNCEMENT_DAY
               <= time.time()
               <= past_launch_time
            )

            display_ph_launch = (
                models.get_display_announcement(web_constants.PRODUCT_HUNT_ANNOUNCEMENT) or is_launching
            ) and not time.time() > past_launch_time
            v13_paper = None
            v13_symbol_charts = []
            if models.get_current_profile().profile_id == "local_ai_trading":
                try:
                    health = json.loads(pathlib.Path("/v13-paper/health.json").read_text())
                    with sqlite3.connect("/v13-paper/v13.sqlite") as connection:
                        history = [
                            {"time": row[0], "value": row[1]}
                            for row in connection.execute(
                                "SELECT bar, equity FROM equity_history ORDER BY bar"
                            )
                        ]
                        fill_rows = list(connection.execute(
                            "SELECT bar, symbol, action, notional, fee FROM orders ORDER BY bar, id"
                        ))
                    fills_by_symbol = {}
                    for fill in fill_rows:
                        fill_symbol = str(fill[1]).split(":", 1)[0].replace("/", "")
                        fills_by_symbol.setdefault(fill_symbol, []).append({
                            "time": fill[0], "action": fill[2],
                            "notional": fill[3], "fee": fill[4],
                        })
                    v13_paper = {**health, "history": history}
                    daily_files = sorted(pathlib.Path("/diversified-forward/daily").glob("*.json.gz"))[-30:]
                    for position in health.get("positions", []):
                        symbol = position["symbol"]
                        points = []
                        for daily_file in daily_files:
                            with gzip.open(daily_file, "rt", encoding="utf-8") as stream:
                                symbols = json.load(stream).get("symbols", {})
                            market = symbols.get(symbol)
                            if market and isinstance(market.get("close"), (int, float)):
                                points.append({"time": daily_file.stem.replace(".json", ""), "value": market["close"]})
                        v13_symbol_charts.append({
                            "symbol": symbol, "points": points,
                            "pnl": position.get("unrealized_pnl", 0),
                            "entry_price": position.get("entry_price"),
                            "fills": fills_by_symbol.get(symbol, []),
                        })
                except (OSError, ValueError, sqlite3.Error):
                    v13_paper = None
            return flask.render_template(
                'index.html',
                has_pnl_history=bool(pnl_symbols),
                watched_symbols=models.get_watched_symbols(),
                backtesting_mode=in_backtesting,
                display_intro=display_intro,
                display_trading_delay_info=trading_delay_info,
                selected_profile=models.get_current_profile().name,
                reference_unit=interfaces_util.get_reference_market(),
                display_time_frame=display_time_frame,
                display_orders=display_orders,
                all_time_frames=all_time_frames,
                user_id=user_id,
                form_to_display=form_to_display,
                display_feedback_form=display_feedback_form,
                sandbox_exchanges=sandbox_exchanges,
                v13_paper=v13_paper,
                v13_symbol_charts=v13_symbol_charts,
                display_ph_launch=display_ph_launch,
                is_launching=is_launching,
                latest_release_url=f"{octobot_commons.constants.GITHUB_BASE_URL}/"
                                   f"{octobot_commons.constants.GITHUB_ORGANISATION}/"
                                   f"{constants.PROJECT_NAME}/releases/latest",
            )
        else:
            return flask.redirect(flask.url_for("terms"))
