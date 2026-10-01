"""Builds custom_components/nilan_mqtt/www/nilan-unit-card.js: the animated drawing of the Comfort 300 LR as a
Home Assistant dashboard card (`type: custom:nilan-unit-card`).

The drawing is made here (layout after the reader's own drawing in web/index.html: right model, outdoor side on the
left) and written into the card as one SVG with a still base layer and layers the card shows by state:
  flow_<level>_<x|bp>  moving air + spinning fans; level 1-4 from the extract fan % (the step the unit really runs);
                       "bp" = fresh air around the exchanger (state "Cooling" or the bypass damper being driven open:
                       the CTS 602 does not report the damper's position)
  heater / defrost / alarm / stopped / winter / summer
Live values are HTML labels on top, formatted by Home Assistant (unit, display precision); a click opens the entity.

Run:  python tools/build_card.py            (also writes tools/card_preview.html with sample values)
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H = 1100, 650
C = dict(bg="#040a12", grid="#0c2433", cyan="#3fd8ff", ink="#c9f4ff", muted="#5fa3bd", out="#36f1cd", sup="#ffb347",
         ext="#ff6a3d", exh="#3f9bff", q="#ffc24a")

E = "sensor.nilan_"
T8, T7, T3, T4 = E + "t8_outdoor", E + "t7_inlet", E + "t3_exhaust", E + "t4_outlet"
STATE, RUNNING, STEP = E + "control_state", "binary_sensor.nilan_running", "select.nilan_ventilation_step"
BYPASS_OPEN, SUMMER = "binary_sensor.nilan_bypass_open", "binary_sensor.nilan_summer"

Y1, Y2 = 190, 370                 # top ducts (air into the unit), bottom ducts (air out of the unit)
# air paths: (path, colour). Fresh air crosses the exchanger top-left -> bottom-right, used air top-right -> bottom-left.
FRESH_IN = (f"M20 {Y1} H400", "out")
FRESH_HX = [(f"M400 {Y1} H470 L550 280", "out"), (f"M550 280 L630 {Y2} H665", "sup")]
FRESH_BP = (f"M400 {Y1} V{Y2 - 9} A9 9 0 0 1 400 {Y2 + 9} V440 H665 V{Y2}", "out")
FRESH_OUT = (f"M665 {Y2} H1080", "sup")
USED = [(f"M1080 {Y1} H630 L550 280", "ext"), (f"M550 280 L470 {Y2} H20", "exh")]
SPEED = {1: (2.6, 1.5), 2: (1.7, 1.0), 3: (1.1, 0.65), 4: (0.75, 0.42)}   # level: (dot cycle s, fan turn s)
# extract fan % per level, limits halfway between the steps (measured 1 Oct 2026 by writing the step: 1 = 25 / 27 %,
# 2 = 39 / 46 %, 3 = 52 / 64 %, 4 = 90 / 100 % supply / extract). Same limits as the HA helper sensor.nilan_actual_step.
FAN_LIMITS = {1: (0.99, 36.5), 2: (36.49, 55), 3: (54.99, 82), 4: (81.99, None)}

STYLE = f"""<style>
text{{font-family:Bahnschrift,"Segoe UI","Roboto Condensed",Arial,sans-serif;letter-spacing:.03em}}
.t{{fill:{C['ink']};font-size:12.5px}}.th{{fill:{C['ink']};font-size:12.5px;font-weight:600;letter-spacing:.12em}}
.ts{{fill:{C['muted']};font-size:11.5px}}.tm{{fill:{C['muted']};font-size:11px;font-family:Consolas,monospace}}
.tp{{fill:{C['muted']};font-size:10.5px;letter-spacing:.14em}}
.hud{{fill:{C['cyan']};font-size:11px;letter-spacing:.2em;font-family:Consolas,monospace}}
.tag{{font-size:15px;font-weight:600;letter-spacing:.2em}}
.duct{{fill:none;stroke-width:18;stroke-linejoin:round;opacity:.17}}
.dim{{opacity:.4}}
.flow{{fill:none;stroke-width:3.4;stroke-linecap:round;stroke-dasharray:2 16;animation:flow linear infinite}}
.mote{{fill:none;stroke-width:2;stroke-linecap:round;stroke-dasharray:1 23;animation:mote linear infinite}}
@keyframes flow{{to{{stroke-dashoffset:-36}}}}@keyframes mote{{to{{stroke-dashoffset:-48}}}}
.box{{fill:#07202e;fill-opacity:.85;stroke:{C['cyan']};stroke-width:1.3}}
.unit{{fill:#061a26;fill-opacity:.55;stroke:{C['cyan']};stroke-width:1.6}}
.hx{{fill:#0a2c3d;fill-opacity:.9;stroke:{C['cyan']};stroke-width:1.3;stroke-linejoin:round}}
.fin{{stroke:{C['cyan']};stroke-width:1;opacity:.22}}
.edge{{stroke:{C['cyan']};stroke-width:1.3;fill:none}}
.frame{{fill:none;stroke:{C['cyan']};stroke-width:2;opacity:.8}}
.dash{{fill:none;stroke:{C['muted']};stroke-width:1.3;stroke-dasharray:7 4}}
.blink{{animation:blink 2.4s ease-in-out infinite}}@keyframes blink{{50%{{opacity:.35}}}}
.spin{{transform-box:fill-box;transform-origin:center;animation:spin 8s linear infinite}}
.spinr{{transform-box:fill-box;transform-origin:center;animation:spin 13s linear infinite reverse}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.ring{{fill:none;stroke:{C['cyan']};stroke-width:1.2;opacity:.55}}
.pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-out infinite}}
@keyframes pulse{{from{{transform:scale(.6);opacity:.9}}to{{transform:scale(2.4);opacity:0}}}}
.panel{{fill:#061a26;fill-opacity:.9;stroke:{C['cyan']};stroke-width:1;opacity:.95}}
.sample{{font-size:13px;font-weight:600;font-family:Consolas,monospace}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
</style>"""
DEFS = f"""<defs>
<pattern id="grid" width="22" height="22" patternUnits="userSpaceOnUse"><path d="M22 0H0V22" fill="none" stroke="{C['grid']}" stroke-width="1"/></pattern>
<radialGradient id="vig" cx="50%" cy="45%" r="70%"><stop offset="55%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".65"/></radialGradient>
<filter id="glow" filterUnits="userSpaceOnUse" x="-50" y="-50" width="2000" height="2000"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<clipPath id="hxclip"><polygon points="470,150 630,150 680,280 630,410 470,410 420,280"/></clipPath></defs>"""


def svg(body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">{STYLE}{DEFS}\n'
            + "\n".join(body) + "\n</svg>")


def text(cls, x, y, s, anchor="start", extra=""):
    return f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}"{extra}>{s}</text>'


def arrow(x, y, d, col):
    rot = {"r": 0, "d": 90, "l": 180, "u": 270}[d]
    return f'<path d="M-6,-6 L5,0 L-6,6 z" fill="{C[col]}" transform="translate({x} {y}) rotate({rot})"/>'


def fan(x, y, col, turn=None):
    """Fan: disc with three blades; `turn` = seconds per turn (None = standing still, faded blades)."""
    style = (f' style="transform-box:fill-box;transform-origin:center;animation:spin {turn}s linear infinite"' if turn
             else ' class="dim"')
    blades = "".join(f'<path d="M{x} {y} q7 -11 0 -15 q-9 5 0 15" fill="{C[col]}" transform="rotate({a} {x} {y})"/>'
                     for a in (0, 120, 240))
    # the invisible circle keeps the group's box centred on the hub, so the spin has no wobble
    return (f'<circle cx="{x}" cy="{y}" r="19" class="box" style="stroke:{C[col]};fill-opacity:1"/>'
            f'<g{style}><circle cx="{x}" cy="{y}" r="16" fill="none"/>{blades}</g>'
            f'<circle cx="{x}" cy="{y}" r="3" fill="{C[col]}"/>')


def air_filter(x):
    zig = " ".join(f"L{x + 5 + 8 * i} {Y1 + (14 if i % 2 else -14)}" for i in range(1, 6))
    return (f'<rect x="{x}" y="{Y1 - 18}" width="50" height="36" rx="2" class="box" style="fill-opacity:1"/>'
            f'<path d="M{x + 5} {Y1 + 14} {zig}" class="edge" style="stroke:{C["muted"]}"/>')


def sensor(x, y, col):
    return f'<circle cx="{x}" cy="{y}" r="5" class="box" style="stroke:{C[col]};fill-opacity:1"/>'


def parts(turn=None):
    """Things that sit on the ducts; drawn again above the moving air so dots pass behind them."""
    return [air_filter(275), air_filter(775), fan(290, Y2, "exh", turn), fan(770, Y2, "sup", turn),
            sensor(365, Y1, "out"), sensor(720, Y1, "ext"), sensor(355, Y2, "exh"), sensor(825, Y2, "sup"),
            f'<rect x="699" y="{Y2 - 20}" width="26" height="40" rx="3" class="box" style="stroke:{C["sup"]};fill-opacity:1"/>'
            f'<path d="M704 {Y2 - 12} h16 m-16 8 h16 m-16 8 h16 m-16 8 h16" class="edge" style="stroke:{C["sup"]};opacity:.6"/>']


def brackets():
    s, L = [], 26
    for (x, y, dx, dy) in [(8, 8, 1, 1), (W - 8, 8, -1, 1), (8, H - 8, 1, -1), (W - 8, H - 8, -1, -1)]:
        s.append(f'<polyline class="frame" points="{x},{y + dy * L} {x},{y} {x + dx * L},{y}"/>')
    return "".join(s)


PANEL = [("MODE", 36, 568), ("STEP SET", 246, 568), ("STEP ACTUAL", 456, 568), ("HUMIDITY", 666, 568),
         ("SUPPLY TARGET", 36, 606), ("SEASON", 246, 606), ("AFTER-HEATER", 456, 606), ("ALARMS", 666, 606)]


def build_base():
    p = [f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>', f'<rect width="{W}" height="{H}" fill="url(#grid)"/>',
         f'<rect width="{W}" height="{H}" fill="url(#vig)"/>', brackets(),
         text("hud", W - 20, 30, "NILAN COMFORT 300 LR // CTS 602", "end"),
         text("hud", 20, 30, "VENTILATION"),
         '<rect x="230" y="110" width="640" height="370" rx="6" class="unit"/>',
         text("ts", 244, 130, "front view · right model"),
         '<path class="dash" d="M225 60 V100 M875 60 V100"/>',
         text("th", 20, 84, "OUTSIDE"), text("th", W - 20, 84, "HOUSE", "end")]
    # exchanger body with plate lines
    p.append('<polygon class="hx" points="470,150 630,150 680,280 630,410 470,410 420,280"/>')
    p.append('<g clip-path="url(#hxclip)">' + "".join(
        f'<line class="fin" x1="{x}" y1="150" x2="{x}" y2="410"/>' for x in range(432, 680, 12)) + '</g>')
    # ducts (bypass thinner), tees
    for d, col in [FRESH_IN, *FRESH_HX, FRESH_OUT, *USED]:
        p.append(f'<path class="duct" d="{d}" stroke="{C[col]}"/>')
    p.append(f'<path class="duct" d="{FRESH_BP[0]}" stroke="{C["out"]}" style="stroke-width:10;stroke-dasharray:9 6"/>')
    p += [f'<circle cx="400" cy="{Y1}" r="4" fill="{C["out"]}"/>', f'<circle cx="665" cy="{Y2}" r="4" fill="{C["sup"]}"/>',
          arrow(120, Y1, "r", "out"), arrow(120, Y2, "l", "exh"), arrow(980, Y1, "l", "ext"), arrow(980, Y2, "r", "sup")]
    p += parts()
    # bypass damper (closed: blade across the duct), condensate drain
    p += ['<rect x="514" y="426" width="32" height="28" rx="3" class="box" style="fill-opacity:1"/>',
          f'<line x1="530" y1="430" x2="530" y2="450" stroke="{C["ink"]}" stroke-width="2.4" stroke-linecap="round"/>',
          f'<path d="M262 480 V500" stroke="{C["muted"]}" stroke-width="3"/>']
    # HUD rings round the exchanger core
    p += ['<circle cx="550" cy="280" r="26" class="ring spin" stroke-dasharray="30 10 5 10"/>',
          '<circle cx="550" cy="280" r="19" class="ring spinr" stroke-dasharray="2 6" style="opacity:.4"/>']
    # panels
    p += ['<rect x="20" y="540" width="840" height="90" rx="3" class="panel"/>',
          f'<rect x="880" y="540" width="200" height="90" rx="3" class="panel" style="stroke:{C["sup"]}"/>']
    t = [text("th", 20, 142, "OUTDOOR AIR · T8"), text("ts", 20, 158, "fresh air in"),
         text("th", 20, 322, "EXHAUST AIR · T4"), text("ts", 20, 338, "used air out"),
         text("th", W - 20, 142, "EXTRACT AIR · T3", "end"), text("ts", W - 20, 158, "used air from the rooms", "end"),
         text("th", W - 20, 322, "SUPPLY AIR · T7", "end"), text("ts", W - 20, 338, "fresh air to the rooms", "end"),
         text("ts", 300, 162, "filter", "middle"), text("ts", 800, 162, "filter", "middle"),
         text("tm", 365, 172, "T8", "middle"), text("tm", 720, 172, "T3 · RH", "middle"),
         text("tm", 355, 352, "T4", "middle"), text("tm", 825, 352, "T7", "middle"),
         text("th", 550, 136, "COUNTER-FLOW HEAT EXCHANGER", "middle"),
         text("tp", 474, 268, "RECOVERY", "middle"), text("tp", 626, 268, "LOSS T3−T7", "middle"),
         text("ts", 290, 410, "extract fan", "middle"), text("ts", 770, 410, "supply fan", "middle"),
         text("ts", 712, 340, "after-heater", "middle"),
         text("ts", 530, 470, "bypass damper", "middle"),
         text("ts", 272, 498, "condensate drain"),
         text("tp", 892, 568, "ROOM · T15"), text("tp", 892, 606, "ROOM SETPOINT")]
    t += [text("tp", x, y + 4, s) for s, x, y in PANEL]
    return p + t


def flows(paths, step):
    dot, _ = SPEED[step]
    out = []
    for d, col in paths:
        out.append(f'<path class="flow" d="{d}" stroke="{C[col]}" style="animation-duration:{dot}s" filter="url(#glow)"/>')
        out.append(f'<path class="mote" d="{d}" stroke="{C["ink"]}" style="animation-duration:{dot * 1.9:.2f}s" '
                   f'transform="translate(0 -5)"/>')
        out.append(f'<path class="mote" d="{d}" stroke="{C[col]}" style="animation-duration:{dot * 1.5:.2f}s" '
                   f'transform="translate(0 5)"/>')
    return out


def build_flow(step, bypass):
    fresh = [FRESH_IN, FRESH_BP, FRESH_OUT] if bypass else [FRESH_IN, *FRESH_HX, FRESH_OUT]
    p = flows(fresh + USED, step) + parts(SPEED[step][1])
    if bypass:   # damper open: blade along the duct, highlighted
        p += ['<rect x="514" y="426" width="32" height="28" rx="3" class="box" style="fill-opacity:1"/>',
              f'<line x1="519" y1="440" x2="541" y2="440" stroke="{C["out"]}" stroke-width="2.4" stroke-linecap="round"/>',
              f'<rect x="510" y="422" width="40" height="36" rx="4" fill="none" stroke="{C["out"]}" class="blink"/>',
              text("tag", 626, 324, "BYPASS", "middle", f' fill="{C["out"]}" style="font-size:11px"')]
    return p


def build_heater():
    return [f'<rect x="699" y="{Y2 - 20}" width="26" height="40" rx="3" fill="{C["ext"]}" fill-opacity=".55" '
            f'stroke="{C["ext"]}" stroke-width="2" filter="url(#glow)" class="blink"/>',
            f'<circle cx="712" cy="{Y2}" r="12" fill="none" stroke="{C["ext"]}" stroke-width="1.5" class="pulse"/>']


OVERLAY_TEXT = {
    "defrost": text("tag", 626, 324, "DEFROST", "middle", f' fill="{C["exh"]}" style="font-size:11px"'),
    "alarm": text("tag", W - 20, 104, "ALARM", "end", f' fill="{C["q"]}"'),
    "stopped": text("tag", 550, 96, "UNIT STOPPED", "middle", f' fill="{C["q"]}"'),
    "winter": text("sample", 366, 610, "WINTER", "start", f' fill="{C["ink"]}"'),
    "summer": text("sample", 366, 610, "SUMMER", "start", f' fill="{C["q"]}"'),
}


# (entity, x, y, colour, align, big, sample value for the preview)
LABELS = [
    (T8, 20, 218, C["out"], "left", True, "14.9 °C"), (T4, 20, 398, C["exh"], "left", True, "16.7 °C"),
    (T3, W - 20, 218, C["ext"], "right", True, "21.4 °C"), (T7, W - 20, 398, C["sup"], "right", True, "20.9 °C"),
    (STATE, W - 20, 54, C["cyan"], "right", True, "Heating"),
    (E + "exchanger_efficiency", 474, 286, C["ink"], "center", True, "56.0 %"),
    (E + "temperature_loss", 626, 286, C["ink"], "center", True, "0.4 °C"),
    (E + "exhaust_fan", 290, 428, C["exh"], "center", False, "100 %"),
    (E + "supply_fan", 770, 428, C["sup"], "center", False, "90 %"),
    ("select.nilan_mode", 156, 568, C["ink"], "left", False, "Auto"),
    (STEP, 366, 568, C["ink"], "left", False, "1"),
    (E + "actual_step", 576, 568, C["cyan"], "left", False, "1"),
    (E + "humidity", 786, 568, C["ink"], "left", False, "65.2 %"),
    (E + "heater_output", 576, 606, C["sup"], "left", False, "0 %"),
    (E + "supply_temp_target", 156, 606, C["sup"], "left", False, "22.0 °C"),
    (E + "alarm_count", 786, 606, C["ink"], "left", False, "0"),
    (E + "t15_room", 1016, 568, C["ink"], "left", False, "25.6 °C"),
    ("number.nilan_temp_setpoint", 1016, 606, C["sup"], "left", False, "22.0 °C"),
]
# ---------- the card ----------
def entity_key(entity_id):
    domain, name = entity_id.split(".", 1)
    return [domain, name.removeprefix("nilan_")]


layers = {"base": build_base(), "heater": build_heater(), **{k: [v] for k, v in OVERLAY_TEXT.items()}}
for step in SPEED:
    for bp in (False, True):
        layers[f"flow_{step}_{'bp' if bp else 'x'}"] = build_flow(step, bp)
css = STYLE.removeprefix("<style>").removesuffix("</style>")
shift = {"left": "0", "center": "-50%", "right": "-100%"}
label_rows = [{"domain": entity_key(e)[0], "key": entity_key(e)[1], "left": f"{x / W * 100:.2f}%", "top": f"{y / H * 100:.2f}%",
               "shift": shift[align], "color": color, "big": big}
              for e, x, y, color, align, big, _sample in LABELS]

CARD = r"""/* Nilan unit card for Home Assistant: animated drawing of the Comfort 300 LR with live values.
   Generated by tools/build_card.py - change the drawing there, not here.

   type: custom:nilan-unit-card
   prefix: nilan            # optional: entity ids are <domain>.<prefix>_<key> (default "nilan")
   entities:                # optional: other entity ids per key, e.g. t8_outdoor: sensor.my_outdoor
*/
const W = __W__, H = __H__;
const CSS = __CSS__;
const DEFS = __DEFS__;
const LAYERS = __LAYERS__;
const LABELS = __LABELS__;
const LEVELS = __LEVELS__;      // [level, extract fan % above, below]

class NilanUnitCard extends HTMLElement {
  static getStubConfig() { return {}; }

  setConfig(config) {
    this._config = config || {};
    this._prefix = this._config.prefix || "nilan";
    this._entities = this._config.entities || {};
  }

  getCardSize() { return 8; }
  getGridOptions() { return { columns: "full" }; }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this._build();
    this._update();
  }

  _id(domain, key) { return this._entities[key] || `${domain}.${this._prefix}_${key}`; }
  _state(domain, key) { const s = this._hass.states[this._id(domain, key)]; return s ? s.state : undefined; }
  _number(domain, key) { return parseFloat(this._state(domain, key)); }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    const layers = Object.entries(LAYERS).map(([name, body]) =>
      `<g id="layer-${name}"${name === "base" ? "" : ' style="display:none"'}>${body}</g>`).join("");
    root.innerHTML = `<style>
      :host { display: block; }
      ha-card { display: block; overflow: hidden; height: 100%; }
      #root { position: relative; }
      svg { display: block; width: 100%; height: auto; }
      .label { position: absolute; cursor: pointer; white-space: nowrap; font-weight: 600;
               font-family: Consolas, 'Roboto Mono', monospace; }
      .label > div { padding: 8px; white-space: nowrap; }
      ${CSS}
    </style>
    <ha-card><div id="root">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}">${DEFS}${layers}</svg>
    </div></ha-card>`;
    const holder = root.getElementById("root");
    this._labels = LABELS.map((l) => {
      const el = document.createElement("div");
      el.className = "label";
      el.style.cssText = `left:${l.left};top:${l.top};transform:translate(${l.shift},-50%);color:${l.color};` +
        `font-size:${l.big ? "clamp(10px, 0.95vw, 16px)" : "clamp(9px, 0.8vw, 13px)"};text-shadow:0 0 6px ${l.color}99`;
      const text = document.createElement("div");
      el.appendChild(text);
      el.addEventListener("click", () => this.dispatchEvent(new CustomEvent("hass-more-info",
        { bubbles: true, composed: true, detail: { entityId: this._id(l.domain, l.key) } })));
      holder.appendChild(el);
      return { ...l, text, shown: null };
    });
    this._layers = Object.fromEntries(Object.keys(LAYERS).filter((n) => n !== "base")
      .map((n) => [n, root.getElementById(`layer-${n}`)]));
  }

  _update() {
    const fan = this._number("sensor", "exhaust_fan");
    let level = 0;
    for (const [n, above, below] of LEVELS) if (fan > above && (below === null || fan < below)) level = n;
    const bypass = this._state("sensor", "control_state") === "Cooling" ||
      this._state("binary_sensor", "bypass_open") === "on";
    const summer = this._state("binary_sensor", "summer");
    const show = {
      heater: this._number("sensor", "heater_output") > 0,
      defrost: this._state("binary_sensor", "defrosting") === "on",
      alarm: this._number("sensor", "alarm_count") > 0,
      stopped: this._state("binary_sensor", "running") === "off",
      winter: summer === "off",
      summer: summer === "on",
    };
    if (level) show[`flow_${level}_${bypass ? "bp" : "x"}`] = true;
    for (const [name, el] of Object.entries(this._layers)) {
      const display = show[name] ? "" : "none";
      if (el.style.display !== display) el.style.display = display;
    }
    for (const l of this._labels) {
      const state = this._hass.states[this._id(l.domain, l.key)];
      const shown = state ? this._hass.formatEntityState(state) : "–";
      if (shown !== l.shown) l.text.textContent = l.shown = shown;
    }
  }
}

if (!customElements.get("nilan-unit-card")) {
  customElements.define("nilan-unit-card", NilanUnitCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "nilan-unit-card", name: "Nilan unit",
    description: "Animated drawing of the Nilan Comfort 300 with live values" });
}
"""

card = (CARD.replace("__W__", str(W)).replace("__H__", str(H))
        .replace("__CSS__", json.dumps(css, ensure_ascii=False))
        .replace("__DEFS__", json.dumps(DEFS, ensure_ascii=False))
        .replace("__LAYERS__", json.dumps({k: "".join(v) for k, v in layers.items()}, ensure_ascii=False))
        .replace("__LABELS__", json.dumps(label_rows, ensure_ascii=False))
        .replace("__LEVELS__", json.dumps([[n, lo, hi] for n, (lo, hi) in FAN_LIMITS.items()])))
www = ROOT / "custom_components" / "nilan_mqtt" / "www"
www.mkdir(parents=True, exist_ok=True)
(www / "nilan-unit-card.js").write_text(card, encoding="utf-8", newline="\n")

# local preview with sample values (no Home Assistant needed)
states = {f"{entity_key(e)[0]}.nilan_{entity_key(e)[1]}": {"state": sample.split(" ")[0], "shown": sample}
          for e, _x, _y, _c, _a, _b, sample in LABELS}
states.update({"binary_sensor.nilan_summer": {"state": "off"}, "binary_sensor.nilan_running": {"state": "on"},
               "binary_sensor.nilan_defrosting": {"state": "off"}, "binary_sensor.nilan_bypass_open": {"state": "off"}})
states["sensor.nilan_exhaust_fan"] = {"state": "46.0", "shown": "46.0 %"}
preview = f"""<!doctype html><meta charset="utf-8"><body style="margin:0;background:#02060b">
<div style="width:1100px"><nilan-unit-card></nilan-unit-card></div>
<script type="module">
import "../custom_components/nilan_mqtt/www/nilan-unit-card.js";
const card = document.querySelector("nilan-unit-card");
card.setConfig({{}});
card.hass = {{ states: {json.dumps(states, ensure_ascii=False)}, formatEntityState: (s) => s.shown ?? s.state }};
</script>"""
(ROOT / "tools" / "card_preview.html").write_text(preview, encoding="utf-8", newline="\n")
print("card bytes:", len(card.encode("utf-8")), "layers:", len(layers), "labels:", len(label_rows))
