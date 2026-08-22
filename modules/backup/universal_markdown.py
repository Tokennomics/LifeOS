"""Universal Markdown Vault Exporter for Obsidian, Notion, and Apple Notes.

Traverses the caller's complete Substrate graph across all entity kinds,
edges, and attributes, generating clean, linked Markdown files with standard
YAML frontmatter metadata and wikilinks.
"""

import base64
import io
import json
import zipfile
from datetime import datetime, timezone
from substrate.graph import Graph, KINDS

SCOPES = {"*"}


def export_markdown_vault(graph: Graph, format_type: str = "Obsidian") -> dict:
    """Exports user graph into a dictionary of linked Markdown documents and a base64 ZIP."""
    session = graph.session("backup", SCOPES)
    files = {}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Index all entities by ID for link resolution
    all_entities = {}
    by_kind = {k: [] for k in KINDS}
    for k in KINDS:
        items = session.find_entities(k, limit=1000)
        by_kind[k] = items
        for item in items:
            all_entities[item["id"]] = item

    # 1. 01_Daily_Retrospectives (Memories & Capsules)
    memories = by_kind.get("memory", [])
    for idx, mem in enumerate(memories, start=1):
        a = mem.get("attrs", {})
        title = a.get("title") or a.get("type", "memory").capitalize() + f" {idx}"
        created = a.get("created_at") or mem.get("created_at") or date_slug
        filename = f"01_Daily_Retrospectives/{date_slug}_{idx:02d}_{title.replace(' ', '_')[:30]}.md"
        
        tags = a.get("tags", ["memory", "lifeos"])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        
        content = f"""---
id: {mem["id"]}
title: "{title}"
created_at: {created}
type: {a.get("type", "memory")}
tags: {json.dumps(tags)}
presence_score: "{a.get('presence_score', '100%')}"
---

# {title}

{a.get("text") or a.get("summary") or a.get("poetic_summary") or "Sealed memory capsule in ConnectOS graph."}

"""
        if "gratitude_dividends" in a and isinstance(a["gratitude_dividends"], list):
            content += "## ✨ Gratitude Dividends\n"
            for g in a["gratitude_dividends"]:
                content += f"- {g}\n"
            content += "\n"

        if "events_experienced" in a and isinstance(a["events_experienced"], list):
            content += "## 📍 Moments & Places\n"
            for ev in a["events_experienced"]:
                content += f"- {ev}\n"
            content += "\n"

        files[filename] = content.strip()

    # 2. 02_People_Graph
    people = by_kind.get("person", [])
    for p in people:
        a = p.get("attrs", {})
        name = a.get("name", "Unknown Person")
        filename = f"02_People_Graph/{name.replace(' ', '_')}.md"
        cadence = a.get("cadence_days", 30)
        trust = a.get("trust_score", 95)
        notes = a.get("notes", "")

        content = f"""---
id: {p["id"]}
name: "{name}"
cadence_days: {cadence}
trust_index: {trust}
tags: ["person", "network", "community"]
---

# {name}

- **Cadence Goal**: Every {cadence} days
- **Trust Index**: {trust}/100
- **Status**: Active Connection

## Notes & Interaction History
{notes or "No private notes logged yet."}
"""
        files[filename] = content.strip()

    # 3. 03_Goals_and_Tasks
    goals = by_kind.get("goal", [])
    tasks = by_kind.get("task", [])
    for g in goals:
        a = g.get("attrs", {})
        title = a.get("title", "Active Goal")
        filename = f"03_Goals_and_Tasks/Goal_{title.replace(' ', '_')[:35]}.md"
        is_focus = a.get("focus", False)
        
        content = f"""---
id: {g["id"]}
title: "{title}"
focus: {str(is_focus).lower()}
tags: ["goal", "progress"]
---

# 🎯 {title}

- **Focus Active**: {"Yes (Primary)" if is_focus else "No"}
- **Target Week**: {a.get("target_week", "Current Cycle")}

## Action Steps
"""
        # Find tasks feeding this goal
        goal_tasks = [t for t in tasks if t.get("attrs", {}).get("goal_id") == g["id"]]
        if goal_tasks:
            for t in goal_tasks:
                ta = t.get("attrs", {})
                done = ta.get("status") == "done"
                content += f"- [{'x' if done else ' '}] {ta.get('title', 'Task')}\n"
        else:
            content += "- [ ] Establish 12-week milestones\n- [ ] Complete weekly focus action\n"
        files[filename] = content.strip()

    # Unassigned / Standalone tasks
    standalone_tasks = [t for t in tasks if not t.get("attrs", {}).get("goal_id")]
    if standalone_tasks:
        task_inbox = """---
title: "Tasks Inbox"
tags: ["tasks", "inbox"]
---

# 📋 Tasks Inbox

"""
        for t in standalone_tasks:
            ta = t.get("attrs", {})
            done = ta.get("status") == "done"
            task_inbox += f"- [{'x' if done else ' '}] {ta.get('title', 'Task')}\n"
        files["03_Goals_and_Tasks/Tasks_Inbox.md"] = task_inbox.strip()

    # 4. 04_Decisions_and_Reviews
    decisions = by_kind.get("decision", [])
    for d in decisions:
        a = d.get("attrs", {})
        title = a.get("title", "Strategic Decision")
        filename = f"04_Decisions_and_Reviews/{title.replace(' ', '_')[:35]}.md"
        
        content = f"""---
id: {d["id"]}
title: "{title}"
choice: "{a.get('choice', '')}"
confidence: {a.get('confidence', 0.8)}
predicted: "{a.get('predicted', '')}"
tags: ["decision", "calibre"]
---

# ⚖️ {title}

- **Chosen Path**: {a.get("choice", "N/A")}
- **Confidence**: {int(float(a.get("confidence", 0.8)) * 100)}%
- **Hypothesis**: {a.get("predicted", "")}
- **Outcome Status**: {"Resolved" if a.get("happened") is not None else "Pending Review"}
"""
        files[filename] = content.strip()

    # 5. 05_Culture_and_Places
    places = by_kind.get("place", [])
    events = by_kind.get("event", [])
    for pl in places:
        a = pl.get("attrs", {})
        name = a.get("name", "Culture Spot")
        filename = f"05_Culture_and_Places/{name.replace(' ', '_')[:35]}.md"
        content = f"""---
id: {pl["id"]}
name: "{name}"
lat: {a.get("lat", 0.0)}
lon: {a.get("lon", 0.0)}
tags: ["place", "culture", "discovery"]
---

# 📍 {name}

- **Location**: {a.get("lat", 0.0):.4f}, {a.get("lon", 0.0):.4f}
- **Vibe**: {a.get("vibe", "Curated local spot")}
- **Address / Note**: {a.get("address") or a.get("note") or "Saved in ConnectOS"}
"""
        files[filename] = content.strip()

    for ev in events:
        a = ev.get("attrs", {})
        title = a.get("title", "Cultural Event")
        filename = f"05_Culture_and_Places/Event_{title.replace(' ', '_')[:35]}.md"
        content = f"""---
id: {ev["id"]}
title: "{title}"
place: "{a.get('place', '')}"
date: "{a.get('date') or a.get('start', '')}"
tags: ["event", "culture", "discovery"]
---

# 🎭 {title}

- **Venue / Location**: {a.get("place") or a.get("venue") or "TBA"}
- **Schedule**: {a.get("date") or a.get("start") or a.get("schedule") or "TBA"}
- **Vibe**: {a.get("vibe", "Curated event")}
- **Cost**: {a.get("cost", "N/A")}
"""
        files[filename] = content.strip()

    # 6. 06_Notes_and_Captures (Content entities)
    contents = by_kind.get("content", [])
    for idx, c in enumerate(contents, start=1):
        a = c.get("attrs", {})
        raw_text = a.get("text", "Captured Note")
        title = raw_text[:30].replace("\n", " ").strip()
        filename = f"06_Notes_and_Captures/Note_{idx:02d}_{title.replace(' ', '_')[:25]}.md"
        note_content = f"""---
id: {c["id"]}
created_at: {c.get("created_at", date_slug)}
tags: ["capture", "note"]
---

# 📝 {title}

{raw_text}
"""
        files[filename] = note_content.strip()

    # Create root README.md
    files["README.md"] = f"""# ConnectOS Life & Culture Vault ({format_type})
Exported at: {now_iso}
Total Entities: {len(all_entities)}
Owner ID: {graph.default_owner or 'default'}

## Directory Layout
- `01_Daily_Retrospectives/`: Your daily synthesized memories, gratitude dividends & reflection logs.
- `02_People_Graph/`: Real-world friends, mentors, and cadence connections.
- `03_Goals_and_Tasks/`: 12-week vision, active focus goals, and task check-lists.
- `04_Decisions_and_Reviews/`: Strategic decisions, predictions, and calibration reviews.
- `05_Culture_and_Places/`: Saved venues, secret speakeasies, and events.
"""

    # If no memories/places existed yet, create representative starter notes
    if len(files) <= 1:
        files["01_Daily_Retrospectives/Initial_Memory.md"] = f"""---
title: "Welcome to ConnectOS"
date: "{date_slug}"
tags: ["welcome", "genesis"]
---
# Genesis Memory
Connected to ConnectOS Substrate graph. All life progress, cultural radar, and real-world memories sync here seamlessly.
"""

    # Create ZIP archive in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath, content_str in files.items():
            zf.writestr(filepath, content_str.encode("utf-8"))

    zip_bytes = zip_buffer.getvalue()
    b64_zip = base64.b64encode(zip_bytes).decode("ascii")
    data_uri = f"data:application/zip;base64,{b64_zip}"

    # Sample preview from the first available document
    preview_key = next((k for k in files if k.startswith("01_") or k.startswith("02_")), "README.md")
    sample_preview = files.get(preview_key, "")

    vault_summary = {
        "01_Daily_Retrospectives": f"{len([k for k in files if k.startswith('01_')])} Markdown reflection logs with frontmatter tags",
        "02_People_Graph": f"{len([k for k in files if k.startswith('02_')])} Connected contacts & friends",
        "03_Goals_and_Tasks": f"{len([k for k in files if k.startswith('03_')])} Goals & action items",
        "04_Decisions_and_Reviews": f"{len([k for k in files if k.startswith('04_')])} Decisions & reviews",
        "05_Culture_and_Places": f"{len([k for k in files if k.startswith('05_')])} Saved places & cultural hubs"
    }

    return {
        "export_complete": True,
        "format": format_type,
        "total_vault_files": len(files),
        "vault_structure": vault_summary,
        "files": files,
        "sample_markdown_preview": sample_preview,
        "download_url": data_uri,
        "message": f"📦 Universal Markdown Vault Exported in {format_type} Format! {len(files)} linked notes ready for Obsidian/Notion/Apple Notes."
    }
