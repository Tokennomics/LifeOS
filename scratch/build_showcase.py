import base64
import os

brain_dir = r"C:\Users\Robert\.gemini\antigravity\brain\f1a3896a-9a54-4222-ae44-05ae053e2621"

def to_b64(fname):
    p = os.path.join(brain_dir, fname)
    with open(p, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")

img_pure_inf_qr = to_b64("infinity_qr_glyph_bold_1788190209333.jpg")
img_circuit_inf_qr = to_b64("infinity_shape_is_qr_master_1788190187042.jpg")
img_inf_wave_int = to_b64("integrated_infinity_wave_master_1788149791163.jpg")
img_tshirt = to_b64("wearable_qr_tshirt_mockup_1788148341758.jpg")
img_scan = to_b64("phone_scanning_tshirt_flow_1788148355856.jpg")

html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    body {{ background: #090d16; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }}
    .card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 16px; transition: transform 0.2s, border-color 0.2s; }}
    .card:hover {{ transform: translateY(-3px); border-color: #38bdf8; }}
    .badge {{ background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8; }}
    .featured {{ border: 2px solid #38bdf8; box-shadow: 0 0 35px rgba(56, 189, 248, 0.3); }}
  </style>
</head>
<body class="p-6">
  <div class="max-w-4xl mx-auto space-y-8">
    <div class="text-center space-y-2">
      <span class="badge px-3 py-1 rounded-full text-xs font-semibold tracking-wider uppercase">The Infinity Sign IS The QR Code</span>
      <h1 class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-sky-400 via-indigo-300 to-purple-400">Pure Infinity Loop QR Code</h1>
      <p class="text-slate-400 text-sm max-w-xl mx-auto">The entire silhouette of the infinity symbol (∞) is constructed out of functional, camera-scannable QR code modules and glowing neon energy contours.</p>
    </div>

    <!-- Featured Pure Infinity QR Designs -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <!-- Pure Infinity QR Bold -->
      <div class="card featured p-5 space-y-3 flex flex-col justify-between">
        <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800 shadow-2xl">
          <img src="{img_pure_inf_qr}" alt="Pure Infinity Sign QR Code" class="w-full h-full object-cover">
        </div>
        <div>
          <div class="flex items-center justify-between mb-1">
            <h3 class="text-lg font-bold text-white">♾️ 1. Pure Infinity QR Glyph</h3>
            <span class="text-xs text-sky-400 font-mono font-bold">High Contrast</span>
          </div>
          <p class="text-xs text-slate-400 leading-relaxed">The entire horizontal figure-8 loop is constructed out of high-contrast QR pixel modules with vibrant neon cyan and solar magenta aura. Clean, iconic, and immediately scannable by smartphone cameras.</p>
        </div>
      </div>

      <!-- Circuit Infinity QR Master -->
      <div class="card featured p-5 space-y-3 flex flex-col justify-between">
        <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800 shadow-2xl">
          <img src="{img_circuit_inf_qr}" alt="Circuit Infinity QR Emblem" class="w-full h-full object-cover">
        </div>
        <div>
          <div class="flex items-center justify-between mb-1">
            <h3 class="text-lg font-bold text-white">♾️ 2. Quantum Circuit Infinity QR</h3>
            <span class="text-xs text-purple-400 font-mono font-bold">Cyberpunk Matrix</span>
          </div>
          <p class="text-xs text-slate-400 leading-relaxed">Continuous infinity ribbon filled with glowing synaptic circuit data tracks and integrated QR finder eyes at the outer loops and center crossing point.</p>
        </div>
      </div>
    </div>

    <!-- T-Shirt & Scanning Interaction Showcase -->
    <div class="space-y-4 pt-4 border-t border-slate-800">
      <h2 class="text-xl font-bold text-white text-center">👕 Physical T-Shirt & Instant Camera Scan Flow</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="card p-4 space-y-2">
          <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800">
            <img src="{img_tshirt}" alt="Wearable T-Shirt Mockup" class="w-full h-full object-cover">
          </div>
          <h4 class="text-sm font-semibold text-white">Heavyweight Streetwear T-Shirt</h4>
          <p class="text-xs text-slate-400">Direct-to-garment (DTG) print on center chest / back with custom interest pills ([AI Research] [Surfing] [Deep Work]).</p>
        </div>

        <div class="card p-4 space-y-2">
          <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800">
            <img src="{img_scan}" alt="Phone Scanning Flow" class="w-full h-full object-cover">
          </div>
          <h4 class="text-sm font-semibold text-white">Instant Scan & Vouch Interaction</h4>
          <p class="text-xs text-slate-400">Point standard iPhone / Android camera at the shirt ➔ Instant profile card popup ➔ 1-Tap Connect (+50 Proximity Karma).</p>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""

out_path = os.path.join(brain_dir, "logo_showcase.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print("Successfully updated logo_showcase.html with Pure Infinity Sign QR logos!")
