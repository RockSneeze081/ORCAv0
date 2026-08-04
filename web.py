#!/usr/bin/env python3
"""Minimal status + WAV-decode web UI for ORCA.

Not a replacement for main.py, and never touches a real Meshtastic
radio -- this is for glancing at the alias table and trying a WAV file
against the decoder from a browser instead of the CLI. Reuses
main.route_packet (and therefore mesh_bridge's actual routing rules)
rather than re-implementing the alias/broadcast/drop logic here, so
this can't silently drift from what main.py --input actually does.

Run:
    python web.py
Then open http://127.0.0.1:5000
"""

import io
import sys
from pathlib import Path

import numpy as np
from flask import Flask, render_template_string, request

sys.path.insert(0, str(Path(__file__).resolve().parent / "decoder"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "bridge"))

import main  # noqa: E402
from mesh_bridge import load_aliases  # noqa: E402

app = Flask(__name__)

PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ORCA</title>
<style>
  :root { --bg: #fff; --fg: #1a1a1a; --border: #ddd; --code-bg: #f2f2f2; --note: #666;
          --warn: #a15c00; --drop: #c53030; --ok: #146c14; --link: #0645ad; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #1a1a1a; --fg: #e8e8e8; --border: #444; --code-bg: #2d2d2d; --note: #aaa;
            --warn: #e0a030; --drop: #ff6b6b; --ok: #4ade80; --link: #7cb0ff; }
  }
  body { font-family: system-ui, sans-serif; max-width: 780px; margin: 2rem auto; padding: 0 1rem;
         background: var(--bg); color: var(--fg); }
  a { color: var(--link); }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
  code { background: var(--code-bg); padding: 0.1rem 0.3rem; border-radius: 3px; }
  .warn { color: var(--warn); }
  .drop { color: var(--drop); }
  .ok { color: var(--ok); }
  .note { color: var(--note); font-size: 0.85rem; }
  input[type=file] { margin: 0.5rem 0; }
  button { padding: 0.4rem 1rem; }
</style>
</head>
<body>
<h1>ORCA</h1>
<p class="note">
  Phase 1, decoder not yet validated against real hardware -- see
  <a href="https://github.com/RockSneeze081/ORCAv0/blob/main/docs/architecture.md">docs/architecture.md</a>.
  This page never sends to a real Meshtastic radio.
</p>

<h2>Aliases ({{ aliases|length }})</h2>
{% if aliases %}
<table>
  <tr><th>name</th><th>node id</th></tr>
  {% for name, node_id in aliases.items()|sort %}
  <tr><td>{{ name }}</td><td><code>{{ node_id }}</code></td></tr>
  {% endfor %}
</table>
{% else %}
<p class="note">No aliases in <code>bridge/alias_store.json</code>. Add one with
  <code>python bridge/manage_aliases.py add &lt;name&gt; &lt;node_id&gt;</code>.</p>
{% endif %}

<h2>Decode a WAV file</h2>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="wav" accept=".wav" required>
  <br>
  <button type="submit">Decode</button>
</form>

{% if error %}
<p class="drop">Error: {{ error }}</p>
{% endif %}

{% if results is not none %}
<p>{{ results|length }} packet(s) found.</p>
{% if results %}
<table>
  <tr><th>type</th><th>text</th><th>routing</th></tr>
  {% for r in results %}
  <tr>
    <td>{{ r.type }}</td>
    <td>{{ r.text }}</td>
    <td class="{{ r.css }}">{{ r.route }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}
{% endif %}

</body>
</html>
"""


class RecordingInterface:
    """Captures what main.route_packet WOULD send; never transmits anything."""

    def __init__(self):
        self.sent = []

    def sendText(self, text, destinationId):
        self.sent.append((text, destinationId))


def _load_wav_as_float32(file_storage):
    from scipy.io import wavfile

    fs, audio = wavfile.read(io.BytesIO(file_storage.read()))
    if audio.ndim > 1:
        audio = audio[:, 0]
    if np.issubdtype(audio.dtype, np.integer):
        audio = audio.astype(np.float32) / 32768.0
    else:
        audio = audio.astype(np.float32)
    return fs, audio


def decode_upload(file_storage, aliases: dict) -> list:
    """Decode an uploaded WAV and describe what main.route_packet did with
    each packet, without actually sending anything (RecordingInterface)."""
    fs, audio = _load_wav_as_float32(file_storage)
    packets = main.decode(audio, fs=fs)

    rows = []
    for packet in packets:
        iface = RecordingInterface()
        main.route_packet(packet, iface, aliases)

        if packet.is_encrypted:
            route, css = "dropped: encrypted, no key management", "drop"
        elif packet.packet_type.name in ("ACK", "INVALID"):
            route, css = f"dropped: {packet.packet_type.name} packet", "drop"
        elif iface.sent:
            text, destination = iface.sent[0]
            route, css = f"-> {destination}", "ok"
        else:
            route, css = "dropped: unknown alias", "warn"

        rows.append(
            {
                "type": packet.packet_type.name,
                "text": packet.text() if not packet.is_encrypted else "(encrypted)",
                "route": route,
                "css": css,
            }
        )
    return rows


@app.route("/", methods=["GET", "POST"])
def index():
    # ALIAS_STORE_PATH lets tests point this at a throwaway file instead of
    # the real bridge/alias_store.json; unset in normal use.
    override = app.config.get("ALIAS_STORE_PATH")
    aliases = load_aliases(override) if override else load_aliases()
    results = None
    error = None

    if request.method == "POST":
        file = request.files.get("wav")
        if not file or not file.filename:
            error = "choose a WAV file first"
        else:
            try:
                results = decode_upload(file, aliases)
            except Exception as exc:  # noqa: BLE001 -- surface any decode failure to the page, not a 500
                error = str(exc)

    return render_template_string(PAGE, aliases=aliases, results=results, error=error)


if __name__ == "__main__":
    app.run(debug=True)
