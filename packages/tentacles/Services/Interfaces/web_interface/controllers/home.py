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
import sqlite3
from octobot.ai_strategy_lab import v13_paper_view, v13_btc_forward_monitor, qwen_shadow_view, v13_analysis, v13_qwen_analysis, v13_universe_view
from octobot.ai_strategy_lab import v13_candidate_shortlist, v13_candidate_data
from octobot.ai_strategy_lab import v13_symbol_charts

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
    @blueprint.route("/v13_comparison")
    @login.login_required_when_activated
    def v13_comparison_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        response = flask.make_response(flask.render_template("v13_comparison_dashboard.html"))
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_paper/charts")
    @login.login_required_when_activated
    def v13_symbol_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        return flask.render_template("v13_symbol_charts.html")

    @blueprint.route("/v13_paper/charts/data")
    @login.login_required_when_activated
    def v13_symbol_dashboard_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            result = v13_symbol_charts.load(flask.request.args.get('symbol'))
        except (OSError, KeyError, TypeError, ValueError, IndexError, sqlite3.Error):
            result = {'available': False, 'message': 'Storico non verificabile per il simbolo richiesto.'}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_candidates/shortlist")
    @login.login_required_when_activated
    def v13_shortlist_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            result = v13_candidate_shortlist.load_public()
            try:
                result['measurements'] = v13_candidate_data.load_public()
            except (OSError, KeyError, TypeError, ValueError):
                result['measurements'] = {'available': False}
        except (OSError, KeyError, IndexError, TypeError, ValueError):
            result = {"available": False}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_candidates")
    @login.login_required_when_activated
    def v13_universe_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        return flask.render_template("v13_universe_dashboard.html")

    @blueprint.route("/v13_candidates/data")
    @login.login_required_when_activated
    def v13_universe_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            result = v13_universe_view.load_view()
        except (OSError, KeyError, IndexError, TypeError, ValueError, EOFError):
            result = {"available": False}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/qwen_shadow")
    @login.login_required_when_activated
    def qwen_shadow_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        return flask.render_template("qwen_shadow_dashboard.html")

    @blueprint.route("/qwen_shadow/data")
    @login.login_required_when_activated
    def qwen_shadow_dashboard_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            result = {"available": True, "shadow": qwen_shadow_view.public_view()}
        except (OSError, KeyError, TypeError, ValueError):
            result = {"available": False}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/btc_research")
    @login.login_required_when_activated
    def btc_research_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        return flask.render_template("btc_research_dashboard.html")

    @blueprint.route("/btc_research/data")
    @login.login_required_when_activated
    def btc_research_dashboard_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            result = {"available": True, "research": v13_btc_forward_monitor.public_view()}
        except (OSError, KeyError, TypeError, ValueError):
            result = {"available": False}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_paper/analysis_snapshot")
    @login.login_required_when_activated
    def v13_analysis_snapshot():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            result = v13_analysis.snapshot(v13_analysis.load_metrics())
        except (OSError, KeyError, TypeError, ValueError, sqlite3.Error):
            return flask.jsonify({"available": False}), 503
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_paper/analysis")
    @login.login_required_when_activated
    def v13_daily_analysis():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        report = v13_qwen_analysis.public_view()
        try:
            metrics = v13_analysis.load_metrics()
            result = {"available": True, "metrics": metrics,
                      "report": report}
        except (OSError, KeyError, TypeError, ValueError, sqlite3.Error):
            result = {"available": False, "report": report}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/v13_paper")
    @login.login_required_when_activated
    def v13_research_dashboard():
        if not models.accepted_terms():
            return flask.redirect(flask.url_for("terms"))
        if models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(404)
        return flask.render_template("v13_research_dashboard.html")

    @blueprint.route("/v13_paper/data")
    @login.login_required_when_activated
    def v13_research_dashboard_data():
        if not models.accepted_terms() or models.get_current_profile().profile_id != "local_ai_trading":
            flask.abort(403)
        try:
            account = v13_paper_view.load_paper_view()
            if account.get("execution_scope") != "RESEARCH_SIMULATION_ONLY":
                raise ValueError("research scope required")
            result = {"account": account, "focus": v13_paper_view.paper_focus(account, {})}
        except (OSError, KeyError, TypeError, ValueError, sqlite3.Error):
            result = {"account": {"available": False}, "focus": {"title": "CONTO NON DISPONIBILE", "description": "Dati del conto non verificabili.", "color": "danger", "next_action": "Il simulatore conserva lo storico; verificare il servizio."}}
        response = flask.jsonify(result)
        response.cache_control.no_store = True
        return response

    @blueprint.route("/")
    @blueprint.route("/home")
    @login.login_required_when_activated
    def home():
        if flask.request.args.get("reset_tutorials", "False") == "True":
            flask_util.BrowsingDataProvider.instance().set_first_displays(True)
        if models.accepted_terms():
            if models.get_current_profile().profile_id == "local_ai_trading" and flask.request.args.get("legacy") != "true":
                try:
                    account = v13_paper_view.load_paper_view()
                    if account.get("execution_scope") == "RESEARCH_SIMULATION_ONLY":
                        return flask.redirect(flask.url_for("v13_research_dashboard"))
                except (OSError, KeyError, TypeError, ValueError, sqlite3.Error):
                    pass
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
            v13_error = None
            v13_paper_focus = None
            if models.get_current_profile().profile_id == "local_ai_trading":
                try:
                    v13_paper = v13_paper_view.load_paper_view()
                    v13_symbol_charts = v13_paper["symbol_charts"]
                    v13_paper_focus = v13_paper_view.paper_focus(v13_paper, {})
                except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as error:
                    v13_paper = None
                    v13_error = str(error)
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
                v13_paper_focus=v13_paper_focus,
                v13_error=v13_error,
                v13_symbol_charts=v13_symbol_charts,
                display_ph_launch=display_ph_launch,
                is_launching=is_launching,
                latest_release_url=f"{octobot_commons.constants.GITHUB_BASE_URL}/"
                                   f"{octobot_commons.constants.GITHUB_ORGANISATION}/"
                                   f"{constants.PROJECT_NAME}/releases/latest",
            )
        else:
            return flask.redirect(flask.url_for("terms"))
