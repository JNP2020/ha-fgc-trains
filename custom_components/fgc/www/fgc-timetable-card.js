/**
 * fgc-timetable-card
 *
 * A Geotren-style ("https://geotren.fgc.cat/isic/<station>") departure
 * board for one FGC station, built from this integration's per-destination
 * sensors (entities carrying a `station_name` attribute matching the
 * configured station). No dependencies — a plain custom element.
 *
 * Card config:
 *   type: custom:fgc-timetable-card
 *   station: Sant Cugat Centre   # must match a sensor's station_name attribute
 *   title: My Station            # optional, defaults to the station name
 *   rows: 4                      # optional, default 4
 */

const BG = "#000000";
const YELLOW = "#ffc629";
const WHITE = "#ffffff";
const DIVIDER = "rgba(255,255,255,0.12)";

/**
 * Collapse departures that clearly represent the same physical train (same
 * line + destination, times within a minute of each other) down to one —
 * a backstop in case the backend ever exposes both a static and a
 * realtime-adjusted entry for what a rider would see as a single train.
 * Prefers the realtime-backed entry when there's a choice.
 */
function _dedupeDepartures(departures) {
  const sorted = [...departures].sort((x, y) => new Date(x.time) - new Date(y.time));
  const kept = [];
  for (const dep of sorted) {
    const time = new Date(dep.time).getTime();
    const dupIdx = kept.findIndex(
      (other) =>
        other.line === dep.line &&
        other.destination === dep.destination &&
        Math.abs(new Date(other.time).getTime() - time) < 60000
    );
    if (dupIdx === -1) {
      kept.push(dep);
    } else if (dep.realtime && !kept[dupIdx].realtime) {
      kept[dupIdx] = dep;
    }
  }
  return kept;
}

class FgcTimetableCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.station) {
      throw new Error("fgc-timetable-card: you must set 'station' (a station's display name) in the card config.");
    }
    this._config = { rows: 4, ...config };
    this._built = false;
    this._departures = [];
  }

  getCardSize() {
    return 1 + (this._config ? this._config.rows : 4);
  }

  static getStubConfig() {
    return { station: "", rows: 4 };
  }

  connectedCallback() {
    if (!this._clockTimer) {
      this._clockTimer = setInterval(() => this._tick(), 1000);
    }
  }

  disconnectedCallback() {
    if (this._clockTimer) {
      clearInterval(this._clockTimer);
      this._clockTimer = null;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
    }
    this._collectDepartures();
    this._renderRows();
  }

  _build() {
    const card = document.createElement("ha-card");
    card.classList.add("fgc-timetable-card");

    const style = document.createElement("style");
    style.textContent = `
      ha-card.fgc-timetable-card {
        background: ${BG};
        overflow: hidden;
        padding: 0;
      }
      .fgc-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 14px 16px 10px;
      }
      .fgc-logo {
        width: 34px;
        height: 34px;
        border-radius: 6px;
        flex-shrink: 0;
      }
      .fgc-title-block {
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .fgc-station-name {
        color: ${WHITE};
        opacity: 0.75;
        font-size: 0.75em;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .fgc-clock {
        color: ${YELLOW};
        font-size: 1.5em;
        font-weight: 600;
        letter-spacing: 0.02em;
        line-height: 1.2;
      }
      .fgc-spacer { flex: 1; }
      .fgc-via-label {
        color: ${YELLOW};
        font-size: 1.1em;
        font-weight: 500;
        padding-right: 4px;
        opacity: 0.9;
      }
      .fgc-row {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 16px;
        border-top: 1px solid ${DIVIDER};
      }
      .fgc-pill {
        flex-shrink: 0;
        min-width: 2.6em;
        box-sizing: border-box;
        text-align: center;
        border-radius: 999px;
        padding: 0.3em 0.7em;
        font-weight: 700;
        font-size: 1.05em;
      }
      .fgc-dest {
        flex: 1;
        min-width: 0;
        color: ${YELLOW};
        font-size: 1.15em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .fgc-live-dot {
        display: inline-block;
        width: 0.4em;
        height: 0.4em;
        margin-left: 0.5em;
        margin-bottom: 0.15em;
        border-radius: 50%;
        background: #4caf50;
        vertical-align: middle;
      }
      .fgc-mins {
        flex-shrink: 0;
        color: ${WHITE};
        font-size: 1.15em;
        min-width: 3.4em;
        text-align: right;
      }
      .fgc-via {
        flex-shrink: 0;
        color: ${WHITE};
        font-size: 1.15em;
        min-width: 1.6em;
        text-align: right;
      }
      .fgc-empty {
        padding: 20px 16px 24px;
        color: ${WHITE};
        opacity: 0.6;
        font-size: 1.05em;
      }
    `;

    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
      <div class="fgc-header">
        <img class="fgc-logo" src="/fgc_static/icon.png" alt="FGC">
        <div class="fgc-title-block">
          <div class="fgc-station-name"></div>
          <div class="fgc-clock">--:--</div>
        </div>
        <div class="fgc-spacer"></div>
        <div class="fgc-via-label">Via</div>
      </div>
      <div class="fgc-rows"></div>
    `;

    card.appendChild(style);
    card.appendChild(wrapper);
    this.innerHTML = "";
    this.appendChild(card);

    this._clockEl = wrapper.querySelector(".fgc-clock");
    this._rowsEl = wrapper.querySelector(".fgc-rows");
    wrapper.querySelector(".fgc-station-name").textContent =
      this._config.title || this._config.station;

    this._tick();
  }

  _tick() {
    if (this._clockEl) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");
      this._clockEl.textContent = `${hh}:${mm}`;
    }
    this._renderRows();
  }

  _collectDepartures() {
    if (!this._hass) return;
    const station = this._config.station;
    const entities = Object.values(this._hass.states).filter(
      (e) =>
        e.entity_id.startsWith("sensor.") &&
        e.attributes &&
        e.attributes.station_name === station
    );
    this._noEntitiesFound = entities.length === 0;

    const departures = [];
    for (const entity of entities) {
      const a = entity.attributes;
      if (a.next_departure) {
        departures.push({
          line: a.line,
          line_color: a.line_color,
          line_text_color: a.line_text_color,
          destination: a.destination,
          platform: a.platform,
          time: a.next_departure,
          realtime: !!a.realtime,
        });
      }
      if (Array.isArray(a.upcoming)) {
        for (const dep of a.upcoming) {
          departures.push({
            line: dep.line,
            line_color: dep.line_color,
            line_text_color: dep.line_text_color,
            destination: dep.destination,
            platform: dep.platform,
            time: dep.next_departure,
            realtime: !!dep.realtime,
          });
        }
      }
    }
    this._departures = _dedupeDepartures(departures).slice(0, this._config.rows);
  }

  _renderRows() {
    if (!this._rowsEl) return;
    this._rowsEl.innerHTML = "";

    if (!this._hass) return;

    const now = Date.now();
    // Defensive re-check independent of how fresh the backend data is: a
    // departure whose time has already passed is never shown, even if it's
    // still sitting in the last data the entities pushed to us.
    const visible = this._departures.filter((dep) => new Date(dep.time).getTime() > now);

    if (visible.length === 0) {
      const empty = document.createElement("div");
      empty.className = "fgc-empty";
      empty.textContent = this._noEntitiesFound
        ? `No FGC sensors found for station "${this._config.station}" — check the name matches exactly (see the sensor's station_name attribute).`
        : "No more departures today";
      this._rowsEl.appendChild(empty);
      return;
    }

    for (const dep of visible) {
      const mins = Math.max(0, Math.round((new Date(dep.time).getTime() - now) / 60000));
      const platform =
        dep.platform !== null && dep.platform !== undefined && dep.platform !== ""
          ? Math.trunc(Number(dep.platform))
          : "";

      const row = document.createElement("div");
      row.className = "fgc-row";

      const pill = document.createElement("div");
      pill.className = "fgc-pill";
      pill.style.background = dep.line_color ? `#${dep.line_color}` : "#666";
      pill.style.color = dep.line_text_color ? `#${dep.line_text_color}` : "#fff";
      pill.textContent = dep.line || "";

      const dest = document.createElement("div");
      dest.className = "fgc-dest";
      dest.textContent = dep.destination || "";
      if (dep.realtime) {
        dest.title = "Live predicted time";
        const liveDot = document.createElement("span");
        liveDot.className = "fgc-live-dot";
        liveDot.title = "Live predicted time";
        dest.appendChild(liveDot);
      }

      const minsEl = document.createElement("div");
      minsEl.className = "fgc-mins";
      minsEl.textContent = `${mins} min`;

      const viaEl = document.createElement("div");
      viaEl.className = "fgc-via";
      viaEl.textContent = platform;

      row.append(pill, dest, minsEl, viaEl);
      this._rowsEl.appendChild(row);
    }
  }
}

customElements.define("fgc-timetable-card", FgcTimetableCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "fgc-timetable-card",
  name: "FGC Timetable",
  description: "Geotren-style live departure board for one FGC station.",
});
