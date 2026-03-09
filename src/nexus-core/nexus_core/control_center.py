"""NexusOS Control Center — GTK3 desktop GUI for managing agents."""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

API_BASE = "http://127.0.0.1:9500"
REFRESH_MS = 3000


def _api(method: str, path: str, body: dict | None = None) -> dict | None:
    """Make a request to the nexus-core API."""
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


CSS = b"""
window { background-color: #1a1a2e; }
.header-bar { background-color: #16213e; border-bottom: 2px solid #0f3460; }
.title-label { color: #00e5ff; font-size: 20px; font-weight: bold; }
.subtitle-label { color: #7f8c8d; font-size: 11px; }
.stat-card { background-color: #16213e; border-radius: 8px; padding: 16px; border: 1px solid #0f3460; }
.stat-value { color: #00e5ff; font-size: 28px; font-weight: bold; }
.stat-title { color: #bdc3c7; font-size: 11px; }
.agent-row { background-color: #16213e; border-radius: 6px; padding: 12px; margin: 4px 0; border: 1px solid #0f3460; }
.agent-name { color: #ecf0f1; font-size: 14px; font-weight: bold; }
.agent-detail { color: #7f8c8d; font-size: 11px; }
.state-running { color: #2ecc71; }
.state-paused { color: #f39c12; }
.state-stopped { color: #e74c3c; }
.state-created { color: #3498db; }
.status-ok { color: #2ecc71; font-size: 12px; font-weight: bold; }
.status-off { color: #e74c3c; font-size: 12px; font-weight: bold; }
.action-button { background-color: #0f3460; color: #ecf0f1; border: 1px solid #00e5ff; border-radius: 4px; padding: 8px 16px; }
.action-button:hover { background-color: #00e5ff; color: #1a1a2e; }
.danger-button { background-color: #c0392b; color: white; border-radius: 4px; padding: 4px 10px; }
.empty-label { color: #7f8c8d; font-size: 14px; }
.log-view { background-color: #0d1117; color: #c9d1d9; font-family: monospace; font-size: 11px; }
"""


class ControlCenter(Gtk.Window):
    def __init__(self):
        super().__init__(title="NexusOS Control Center")
        self.set_default_size(900, 620)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Apply CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Main layout
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(16)
        header.set_margin_bottom(16)
        header.get_style_context().add_class("header-bar")

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label="NexusOS Control Center")
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class("title-label")
        title_box.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="Autonomous Agent Orchestration")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.get_style_context().add_class("subtitle-label")
        title_box.pack_start(subtitle, False, False, 0)

        header.pack_start(title_box, True, True, 0)

        self._daemon_status = Gtk.Label(label="DAEMON: CHECKING...")
        self._daemon_status.get_style_context().add_class("status-off")
        header.pack_end(self._daemon_status, False, False, 0)

        vbox.pack_start(header, False, False, 0)

        # Stats row
        stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        stats_box.set_margin_start(20)
        stats_box.set_margin_end(20)
        stats_box.set_margin_bottom(12)
        stats_box.set_homogeneous(True)

        self._stat_agents = self._make_stat_card("0", "Active Agents")
        self._stat_max = self._make_stat_card("--", "Max Concurrent")
        self._stat_decisions = self._make_stat_card("0", "Decisions Made")
        self._stat_credits = self._make_stat_card("0", "Credits Consumed")

        stats_box.pack_start(self._stat_agents, True, True, 0)
        stats_box.pack_start(self._stat_max, True, True, 0)
        stats_box.pack_start(self._stat_decisions, True, True, 0)
        stats_box.pack_start(self._stat_credits, True, True, 0)
        vbox.pack_start(stats_box, False, False, 0)

        # Action buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_start(20)
        btn_box.set_margin_end(20)
        btn_box.set_margin_bottom(12)

        spawn_btn = Gtk.Button(label="Spawn New Agent")
        spawn_btn.get_style_context().add_class("action-button")
        spawn_btn.connect("clicked", self._on_spawn_clicked)
        btn_box.pack_start(spawn_btn, False, False, 0)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.get_style_context().add_class("action-button")
        refresh_btn.connect("clicked", lambda _: self._refresh())
        btn_box.pack_start(refresh_btn, False, False, 0)

        vbox.pack_start(btn_box, False, False, 0)

        # Agent list (scrollable)
        scroll = Gtk.ScrolledWindow()
        scroll.set_margin_start(20)
        scroll.set_margin_end(20)
        scroll.set_margin_bottom(16)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._agent_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._empty_label = Gtk.Label(label="No agents running. Click 'Spawn New Agent' to get started.")
        self._empty_label.get_style_context().add_class("empty-label")
        self._empty_label.set_margin_top(40)
        self._agent_list.pack_start(self._empty_label, False, False, 0)

        scroll.add(self._agent_list)
        vbox.pack_start(scroll, True, True, 0)

        # Start refresh timer
        self._refresh()
        GLib.timeout_add(REFRESH_MS, self._refresh_tick)

    def _make_stat_card(self, value: str, title: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class("stat-card")
        card.set_halign(Gtk.Align.FILL)

        val_label = Gtk.Label(label=value)
        val_label.get_style_context().add_class("stat-value")
        card.pack_start(val_label, False, False, 4)

        title_label = Gtk.Label(label=title)
        title_label.get_style_context().add_class("stat-title")
        card.pack_start(title_label, False, False, 4)

        card._value_label = val_label
        return card

    def _refresh_tick(self) -> bool:
        self._refresh()
        return True  # keep timer alive

    def _refresh(self):
        status = _api("GET", "/api/status")
        if status is None:
            self._daemon_status.set_text("DAEMON: OFFLINE")
            self._daemon_status.get_style_context().remove_class("status-ok")
            self._daemon_status.get_style_context().add_class("status-off")
            return

        self._daemon_status.set_text("DAEMON: ONLINE")
        self._daemon_status.get_style_context().remove_class("status-off")
        self._daemon_status.get_style_context().add_class("status-ok")

        agents = status.get("agents", {})
        total = status.get("total_agents", 0)
        max_ag = status.get("max_agents", 0)
        total_decisions = sum(a.get("decisions_made", 0) for a in agents.values())
        total_credits = sum(a.get("credits_used", 0) for a in agents.values())

        self._stat_agents._value_label.set_text(str(total))
        self._stat_max._value_label.set_text(str(max_ag))
        self._stat_decisions._value_label.set_text(str(total_decisions))
        self._stat_credits._value_label.set_text(f"{total_credits:.0f}")

        # Rebuild agent list
        for child in self._agent_list.get_children():
            self._agent_list.remove(child)

        if not agents:
            self._agent_list.pack_start(self._empty_label, False, False, 0)
            self._empty_label.show()
        else:
            for agent_id, agent in agents.items():
                row = self._make_agent_row(agent_id, agent)
                self._agent_list.pack_start(row, False, False, 0)

        self._agent_list.show_all()

    def _make_agent_row(self, agent_id: str, agent: dict) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.get_style_context().add_class("agent-row")

        # Info column
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        name_label = Gtk.Label(label=agent.get("name", "unnamed"))
        name_label.set_halign(Gtk.Align.START)
        name_label.get_style_context().add_class("agent-name")
        info.pack_start(name_label, False, False, 0)

        state = agent.get("state", "unknown")
        state_label = Gtk.Label(label=f"State: {state.upper()}  |  ID: {agent_id[:12]}")
        state_label.set_halign(Gtk.Align.START)
        state_label.get_style_context().add_class("agent-detail")
        state_label.get_style_context().add_class(f"state-{state}")
        info.pack_start(state_label, False, False, 0)

        used = agent.get("credits_used", 0)
        remaining = agent.get("credits_remaining", 0) if "credits_remaining" in agent else 0
        budget = used + remaining
        detail = f"Credits: {used:.0f}/{budget:.0f} used  |  Decisions: {agent.get('decisions_made', 0)}"
        detail_label = Gtk.Label(label=detail)
        detail_label.set_halign(Gtk.Align.START)
        detail_label.get_style_context().add_class("agent-detail")
        info.pack_start(detail_label, False, False, 0)

        row.pack_start(info, True, True, 0)

        # Action buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        btn_box.set_valign(Gtk.Align.CENTER)

        goal_btn = Gtk.Button(label="Send Goal")
        goal_btn.get_style_context().add_class("action-button")
        goal_btn.connect("clicked", lambda _, aid=agent_id: self._on_send_goal(aid))
        btn_box.pack_start(goal_btn, False, False, 0)

        stop_btn = Gtk.Button(label="Stop")
        stop_btn.get_style_context().add_class("danger-button")
        stop_btn.connect("clicked", lambda _, aid=agent_id: self._on_stop_agent(aid))
        btn_box.pack_start(stop_btn, False, False, 0)

        row.pack_end(btn_box, False, False, 0)
        return row

    def _on_spawn_clicked(self, _button):
        dialog = SpawnDialog(self)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            name = dialog.get_name()
            budget = dialog.get_budget()
            result = _api("POST", "/api/agents", {
                "name": name,
                "credit_budget": budget,
            })
            if result and "error" not in result:
                self._show_info(f"Agent '{name}' spawned successfully!\nID: {result.get('agent_id', 'unknown')}")
            else:
                err = result.get("error", "Unknown error") if result else "Daemon not responding"
                self._show_error(f"Failed to spawn agent: {err}")
        dialog.destroy()
        self._refresh()

    def _on_send_goal(self, agent_id: str):
        dialog = GoalDialog(self)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            goal = dialog.get_goal()
            if goal:
                result = _api("POST", f"/api/agents/{agent_id}/goal", {"goal": goal})
                if result and "error" not in result:
                    self._show_info(f"Goal submitted to agent {agent_id[:12]}.")
                else:
                    err = result.get("error", "Unknown error") if result else "Failed"
                    self._show_error(f"Failed: {err}")
        dialog.destroy()

    def _on_stop_agent(self, agent_id: str):
        result = _api("DELETE", f"/api/agents/{agent_id}")
        self._refresh()

    def _show_info(self, message: str):
        d = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        d.run()
        d.destroy()

    def _show_error(self, message: str):
        d = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        d.run()
        d.destroy()


class SpawnDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(
            title="Spawn New Agent",
            transient_for=parent,
            modal=True,
        )
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Spawn", Gtk.ResponseType.OK,
        )
        self.set_default_size(400, 200)

        area = self.get_content_area()
        area.set_spacing(12)
        area.set_margin_start(16)
        area.set_margin_end(16)
        area.set_margin_top(12)

        # Agent name
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_box.pack_start(Gtk.Label(label="Agent Name:"), False, False, 0)
        self._name_entry = Gtk.Entry()
        self._name_entry.set_text("new-agent")
        self._name_entry.set_hexpand(True)
        name_box.pack_start(self._name_entry, True, True, 0)
        area.pack_start(name_box, False, False, 0)

        # Credit budget
        budget_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        budget_box.pack_start(Gtk.Label(label="Credit Budget:"), False, False, 0)
        self._budget_spin = Gtk.SpinButton.new_with_range(100, 100000, 100)
        self._budget_spin.set_value(1000)
        budget_box.pack_start(self._budget_spin, True, True, 0)
        area.pack_start(budget_box, False, False, 0)

        self.show_all()

    def get_name(self) -> str:
        return self._name_entry.get_text().strip() or "unnamed"

    def get_budget(self) -> float:
        return self._budget_spin.get_value()


class GoalDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(
            title="Send Goal to Agent",
            transient_for=parent,
            modal=True,
        )
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Submit", Gtk.ResponseType.OK,
        )
        self.set_default_size(500, 200)

        area = self.get_content_area()
        area.set_spacing(12)
        area.set_margin_start(16)
        area.set_margin_end(16)
        area.set_margin_top(12)

        area.pack_start(Gtk.Label(label="Describe the goal for this agent:"), False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(80)
        self._text = Gtk.TextView()
        self._text.set_wrap_mode(Gtk.WrapMode.WORD)
        scroll.add(self._text)
        area.pack_start(scroll, True, True, 0)

        self.show_all()

    def get_goal(self) -> str:
        buf = self._text.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()


def main():
    win = ControlCenter()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
