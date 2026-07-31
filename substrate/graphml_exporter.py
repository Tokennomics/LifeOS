"""Professional GraphML Topology Exporter.

Exports the substrate graph nodes and edges as standard GraphML XML files.
"""

import xml.etree.ElementTree as ET
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def export_graphml(graph: Graph) -> str:
    """Compiles the database graph into standard GraphML format."""
    session = graph.session(MODULE, SCOPES)

    # Fetch all entities
    kinds = ["admin_item", "content", "decision", "event", "goal", "interest", "memory", "metric", "person", "place", "task"]
    entities = []
    for k in kinds:
        try:
            entities.extend(session.find_entities(k, limit=2000))
        except Exception:
            pass

    # Build GraphML XML structure
    root = ET.Element("graphml", {
        "xmlns": "http://graphml.graphdrawing.org/xmlns",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd"
    })

    # Define attributes keys
    key_kind = ET.SubElement(root, "key", {
        "id": "kind", "for": "node", "attr.name": "kind", "attr.type": "string"
    })
    key_label = ET.SubElement(root, "key", {
        "id": "label", "for": "node", "attr.name": "label", "attr.type": "string"
    })
    key_rel = ET.SubElement(root, "key", {
        "id": "rel", "for": "edge", "attr.name": "rel", "attr.type": "string"
    })

    graph_el = ET.SubElement(root, "graph", {
        "id": "G", "edgedefault": "directed"
    })

    # Add nodes
    for entity in entities:
        node = ET.SubElement(graph_el, "node", {"id": entity["id"]})
        
        # Add kind data
        d_kind = ET.SubElement(node, "data", {"key": "kind"})
        d_kind.text = entity["kind"]
        
        # Add label data
        attrs = entity.get("attrs", {})
        label_text = attrs.get("name") or attrs.get("title") or entity["kind"]
        d_label = ET.SubElement(node, "data", {"key": "label"})
        d_label.text = str(label_text)

    # Fetch edges from database
    conn = session.graph.conn
    cur = conn.cursor()
    cur.execute("SELECT id, src, dst, rel FROM edges")
    edges = cur.fetchall()

    # Add edges
    for edge_id, src, dst, rel in edges:
        edge_el = ET.SubElement(graph_el, "edge", {
            "id": edge_id,
            "source": src,
            "target": dst
        })
        d_rel = ET.SubElement(edge_el, "data", {"key": "rel"})
        d_rel.text = rel

    # Convert to XML string
    ET.indent(root, space="  ", level=0)
    xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_str.decode("utf-8")
