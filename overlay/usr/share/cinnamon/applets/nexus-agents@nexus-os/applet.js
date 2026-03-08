/**
 * NexusOS Agent Monitor — Cinnamon Panel Applet
 *
 * Displays active agent count in the panel and provides a dropdown
 * showing each agent's status, credit usage, and recent decisions.
 * Communicates with nexus-core daemon via its local HTTP API.
 */

const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const St = imports.gi.St;
const Soup = imports.gi.Soup;
const GLib = imports.gi.GLib;
const Mainloop = imports.mainloop;
const Lang = imports.lang;
const Settings = imports.ui.settings;

const NEXUS_API = "http://127.0.0.1:9500";
const REFRESH_INTERVAL = 5; // seconds

class NexusAgentApplet extends Applet.TextIconApplet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);

        this.metadata = metadata;
        this.instanceId = instanceId;

        this.set_applet_icon_name("system-run");
        this.set_applet_label("Nexus: --");
        this.set_applet_tooltip("NexusOS Agent Monitor");

        // Build popup menu
        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menuManager.addMenu(this.menu);

        this._buildMenu();

        // Start polling
        this._session = new Soup.Session();
        this._refreshLoop();
    }

    _buildMenu() {
        // Header
        let header = new PopupMenu.PopupMenuItem("NexusOS Agent Monitor", {
            reactive: false,
            style_class: "nexus-header",
        });
        this.menu.addMenuItem(header);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Agent list (populated dynamically)
        this._agentSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._agentSection);

        // No agents placeholder
        this._noAgentsItem = new PopupMenu.PopupMenuItem("No agents running", {
            reactive: false,
        });
        this._agentSection.addMenuItem(this._noAgentsItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // System credits
        this._creditsItem = new PopupMenu.PopupMenuItem("Credits: --/--", {
            reactive: false,
        });
        this.menu.addMenuItem(this._creditsItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Actions
        let controlCenter = new PopupMenu.PopupMenuItem("Open Control Center");
        controlCenter.connect("activate", () => {
            GLib.spawn_command_line_async(
                "/opt/nexus/venv/bin/python3 -m nexus_core.dashboard"
            );
        });
        this.menu.addMenuItem(controlCenter);

        let spawnAgent = new PopupMenu.PopupMenuItem("Spawn New Agent...");
        spawnAgent.connect("activate", () => {
            GLib.spawn_command_line_async(
                "/opt/nexus/venv/bin/nexus-core spawn --interactive"
            );
        });
        this.menu.addMenuItem(spawnAgent);
    }

    _refreshLoop() {
        this._fetchStatus();
        this._timeout = Mainloop.timeout_add_seconds(
            REFRESH_INTERVAL,
            () => {
                this._fetchStatus();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    _fetchStatus() {
        try {
            let message = Soup.Message.new("GET", `${NEXUS_API}/api/status`);
            if (!message) {
                this.set_applet_label("Nexus: OFF");
                return;
            }

            this._session.send_and_read_async(
                message,
                GLib.PRIORITY_DEFAULT,
                null,
                (session, result) => {
                    try {
                        let bytes = session.send_and_read_finish(result);
                        let text = new TextDecoder().decode(bytes.get_data());
                        let status = JSON.parse(text);
                        this._updateDisplay(status);
                    } catch (e) {
                        this.set_applet_label("Nexus: OFF");
                    }
                }
            );
        } catch (e) {
            this.set_applet_label("Nexus: OFF");
        }
    }

    _updateDisplay(status) {
        let agentCount = status.total_agents || 0;
        let maxAgents = status.max_agents || 0;

        // Update panel label
        this.set_applet_label(`Nexus: ${agentCount}/${maxAgents}`);

        if (agentCount > 0) {
            this.set_applet_icon_name("system-run");
        } else {
            this.set_applet_icon_name("system-run-symbolic");
        }

        // Update agent list in menu
        this._agentSection.removeAll();

        let agents = status.agents || {};
        let agentIds = Object.keys(agents);

        if (agentIds.length === 0) {
            this._agentSection.addMenuItem(
                new PopupMenu.PopupMenuItem("No agents running", {
                    reactive: false,
                })
            );
            return;
        }

        for (let agentId of agentIds) {
            let agent = agents[agentId];
            let stateIcon = this._stateIcon(agent.state);
            let label = `${stateIcon} ${agent.name} — ${agent.credits_used.toFixed(0)}/${(agent.credits_used + agent.credits_remaining).toFixed(0)} credits`;

            let item = new PopupMenu.PopupMenuItem(label);
            item.connect("activate", () => {
                // Open agent detail view
                GLib.spawn_command_line_async(
                    `/opt/nexus/venv/bin/nexus-core inspect ${agentId}`
                );
            });
            this._agentSection.addMenuItem(item);
        }
    }

    _stateIcon(state) {
        switch (state) {
            case "running":
                return "\u25B6"; // play triangle
            case "paused":
                return "\u23F8"; // pause
            case "stopped":
                return "\u25A0"; // stop square
            case "error":
                return "\u26A0"; // warning
            default:
                return "\u25CB"; // circle
        }
    }

    on_applet_clicked(event) {
        this.menu.toggle();
    }

    on_applet_removed_from_panel() {
        if (this._timeout) {
            Mainloop.source_remove(this._timeout);
            this._timeout = null;
        }
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    return new NexusAgentApplet(metadata, orientation, panelHeight, instanceId);
}
