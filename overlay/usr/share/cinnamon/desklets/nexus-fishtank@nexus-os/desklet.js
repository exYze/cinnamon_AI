/**
 * NexusOS Fish Tank Desklet
 *
 * A desktop widget that visualizes active agents as "fish" swimming
 * in a tank. Each agent is represented as a node showing its name,
 * current task, confidence level, and credit usage. Decision trees
 * are drawn as connecting lines between parent/child tasks.
 *
 * This is the 2D desktop version of the "Fish Tank" concept.
 * The full VR/AR spatial computing version is planned for Phase 2.
 */

const Desklet = imports.ui.desklet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const GLib = imports.gi.GLib;
const Soup = imports.gi.Soup;
const Mainloop = imports.mainloop;
const Cairo = imports.cairo;

const NEXUS_API = "http://127.0.0.1:9500";
const REFRESH_INTERVAL = 3;
const TANK_WIDTH = 580;
const TANK_HEIGHT = 380;

class NexusFishTankDesklet extends Desklet.Desklet {
    constructor(metadata, deskletId) {
        super(metadata, deskletId);
        this.metadata = metadata;

        this._setupUI();
        this._session = new Soup.Session();
        this._agents = {};
        this._agentPositions = {};

        this._startRefresh();
    }

    _setupUI() {
        // Main container
        this._container = new St.BoxLayout({
            vertical: true,
            style_class: "nexus-fishtank-container",
            style:
                "background-color: rgba(10, 15, 30, 0.92);" +
                "border: 2px solid rgba(0, 180, 255, 0.6);" +
                "border-radius: 12px;" +
                "padding: 10px;" +
                "width: 600px;" +
                "height: 400px;",
        });

        // Title bar
        let titleBar = new St.BoxLayout({
            style:
                "padding-bottom: 8px;" +
                "border-bottom: 1px solid rgba(0, 180, 255, 0.3);",
        });

        let title = new St.Label({
            text: "NEXUS FISH TANK",
            style:
                "color: rgba(0, 200, 255, 0.9);" +
                "font-size: 13px;" +
                "font-weight: bold;" +
                "letter-spacing: 3px;",
        });
        titleBar.add_child(title);

        this._statusLabel = new St.Label({
            text: "  |  OFFLINE",
            style:
                "color: rgba(255, 100, 100, 0.8);" +
                "font-size: 11px;" +
                "padding-left: 10px;",
        });
        titleBar.add_child(this._statusLabel);

        this._container.add_child(titleBar);

        // Agent display area
        this._tankArea = new St.BoxLayout({
            vertical: true,
            style:
                "padding: 8px;" +
                "margin-top: 8px;",
        });

        this._agentLabels = {};
        this._placeholder = new St.Label({
            text: "\n  No agents are currently active.\n\n  Start an agent with:\n  $ nexus-core spawn --name worker-1",
            style:
                "color: rgba(100, 140, 180, 0.7);" +
                "font-size: 12px;" +
                "font-family: monospace;",
        });
        this._tankArea.add_child(this._placeholder);

        this._container.add_child(this._tankArea);

        this.setContent(this._container);
    }

    _startRefresh() {
        this._fetchStatus();
        this._timeout = Mainloop.timeout_add_seconds(REFRESH_INTERVAL, () => {
            this._fetchStatus();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _fetchStatus() {
        try {
            let message = Soup.Message.new("GET", `${NEXUS_API}/api/status`);
            if (!message) {
                this._setOffline();
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
                        this._updateTank(status);
                    } catch (e) {
                        this._setOffline();
                    }
                }
            );
        } catch (e) {
            this._setOffline();
        }
    }

    _setOffline() {
        this._statusLabel.set_text("  |  OFFLINE");
        this._statusLabel.set_style(
            "color: rgba(255, 100, 100, 0.8); font-size: 11px; padding-left: 10px;"
        );
    }

    _updateTank(status) {
        let agents = status.agents || {};
        let agentIds = Object.keys(agents);

        // Update status
        this._statusLabel.set_text(
            `  |  ONLINE  |  ${agentIds.length}/${status.max_agents} agents`
        );
        this._statusLabel.set_style(
            "color: rgba(100, 255, 150, 0.8); font-size: 11px; padding-left: 10px;"
        );

        // Clear tank
        this._tankArea.destroy_all_children();

        if (agentIds.length === 0) {
            this._tankArea.add_child(this._placeholder);
            return;
        }

        // Render each agent as a "fish" card
        for (let agentId of agentIds) {
            let agent = agents[agentId];
            let card = this._createAgentCard(agentId, agent);
            this._tankArea.add_child(card);
        }
    }

    _createAgentCard(agentId, agent) {
        let stateColor = this._getStateColor(agent.state);
        let budgetTotal = agent.credits_used + agent.credits_remaining;
        let budgetPct = budgetTotal > 0
            ? ((agent.credits_remaining / budgetTotal) * 100).toFixed(0)
            : 0;

        let card = new St.BoxLayout({
            vertical: false,
            style:
                `background-color: rgba(20, 30, 50, 0.8);` +
                `border-left: 3px solid ${stateColor};` +
                `border-radius: 6px;` +
                `padding: 8px 12px;` +
                `margin-bottom: 6px;`,
        });

        // Agent info column
        let info = new St.BoxLayout({ vertical: true });

        let nameLabel = new St.Label({
            text: `${agent.name}`,
            style: `color: rgba(220, 230, 255, 0.95); font-size: 13px; font-weight: bold;`,
        });
        info.add_child(nameLabel);

        let detailLabel = new St.Label({
            text: `${agent.state.toUpperCase()}  |  ${agent.decisions_made} decisions  |  ${budgetPct}% budget remaining`,
            style: `color: rgba(140, 160, 200, 0.7); font-size: 10px; margin-top: 2px;`,
        });
        info.add_child(detailLabel);

        card.add_child(info);
        return card;
    }

    _getStateColor(state) {
        switch (state) {
            case "running":  return "rgba(0, 220, 130, 0.9)";
            case "paused":   return "rgba(255, 200, 50, 0.9)";
            case "stopped":  return "rgba(150, 150, 170, 0.6)";
            case "error":    return "rgba(255, 80, 80, 0.9)";
            default:         return "rgba(100, 140, 200, 0.6)";
        }
    }

    on_desklet_removed() {
        if (this._timeout) {
            Mainloop.source_remove(this._timeout);
            this._timeout = null;
        }
    }
}

function main(metadata, deskletId) {
    return new NexusFishTankDesklet(metadata, deskletId);
}
