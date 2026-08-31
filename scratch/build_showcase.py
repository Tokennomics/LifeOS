import base64
import os

brain_dir = r"C:\Users\Robert\.gemini\antigravity\brain\f1a3896a-9a54-4222-ae44-05ae053e2621"

def to_b64(fname):
    p = os.path.join(brain_dir, fname)
    with open(p, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")

img_integrated_master = to_b64("integrated_qr_logo_master_1788149399928.jpg")
img_integrated_squircle = to_b64("integrated_qr_glyph_minimal_1788149426478.jpg")
img_nexus = to_b64("logo_concept_quantum_nexus_1788148702818.jpg")
img_wave = to_b64("logo_concept_infinity_wave_1788148716318.jpg")
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
    .featured {{ border: 2px solid #38bdf8; box-shadow: 0 0 25px rgba(56, 189, 248, 0.2); }}
  </style>
</head>
<body class="p-6">
  <div class="max-w-4xl mx-auto space-y-8">
    <div class="text-center space-y-2">
      <span class="badge px-3 py-1 rounded-full text-xs font-semibold tracking-wider uppercase">Natively Integrated QR Logos</span>
      <h1 class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-sky-400 via-indigo-300 to-purple-400">The QR Code IS The Logo</h1>
      <p class="text-slate-400 text-sm max-w-xl mx-auto">Seamless fusion where the logo geometry itself forms a high-contrast scannable QR code matrix.</p>
    </div>

    <!-- Featured Natively Integrated QR Logos -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <!-- Master Integrated QR -->
      <div class="card featured p-5 space-y-3 flex flex-col justify-between">
        <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800 shadow-2xl">
          <img src="{img_integrated_master}" alt="Master Integrated QR Logo" class="w-full h-full object-cover">
        </div>
        <div>
          <div class="flex items-center justify-between mb-1">
            <h3 class="text-lg font-bold text-white">✨ Quantum Circuit QR Emblem</h3>
            <span class="text-xs text-amber-400 font-mono font-bold">Recommended</span>
          </div>
          <p class="text-xs text-slate-400 leading-relaxed">The 3 corner finder eyes are glowing solar/cyan nodes. The internal data modules are sleek synaptic circuit traces. Instantly scannable by iPhone & Android cameras while looking like a sacred-tech crest.</p>
        </div>
      </div>

      <!-- Squircle Integrated QR -->
      <div class="card featured p-5 space-y-3 flex flex-col justify-between">
        <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800 shadow-2xl">
          <img src="{img_integrated_squircle}" alt="Minimalist Squircle QR Glyph" class="w-full h-full object-cover">
        </div>
        <div>
          <div class="flex items-center justify-between mb-1">
            <h3 class="text-lg font-bold text-white">📱 Squircle App Icon QR</h3>
            <span class="text-xs text-sky-400 font-mono font-bold">App Store Ready</span>
          </div>
          <p class="text-xs text-slate-400 leading-relaxed">Apple iOS squircle frame with concentric glowing radar rings in the corners and matrix dots inside. Perfect for modern mobile app icons and front-pocket streetwear prints.</p>
        </div>
      </div>
    </div>

    <!-- Secondary Variations -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
      <div class="card p-4 space-y-2">
        <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800">
          <img src="{img_nexus}" alt="Quantum Nexus Matrix" class="w-full h-full object-cover">
        </div>
        <h4 class="text-sm font-semibold text-white">Quantum Nexus (Hexagonal Web)</h4>
        <p class="text-xs text-slate-400">Radial sacred-network geometry with centered QR target.</p>
      </div>

      <div class="card p-4 space-y-2">
        <div class="rounded-xl overflow-hidden aspect-square bg-slate-950 border border-slate-800">
          <img src="{img_wave}" alt="Infinity Wave" class="w-full h-full object-cover">
        </div>
        <h4 class="text-sm font-semibold text-white">Infinity Wave (Synergy Ribbons)</h4>
        <p class="text-xs text-slate-400">Interlocking fluid ribbons wrapping around the QR square.</p>
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
          <p class="text-xs text-slate-400">Direct-to-garment (DTG) print with custom interest pills ([AI Research] [Surfing] [Deep Work]).</p>
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
print("Successfully updated logo_showcase.html with integrated QR logos!")
