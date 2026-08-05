import pytest
from gateway import accounts
from modules.crews import crews
from modules.comms import bulletin, chatroom, gallery, collage, chat
from modules.convoy import events_ingest
from substrate.graph import Graph

PW = "correct-horse-battery"

@pytest.fixture
def world(graph):
    """Ana (Lisbon local), Bruno (member), and Charlie (stranger) as three accounts."""
    ana = accounts.register(graph, "ana", PW)
    bruno = accounts.register(graph, "bruno", PW)
    charlie = accounts.register(graph, "charlie", PW)
    return {
        "ana": Graph(graph.conn, graph.bus, default_owner=ana["owner_id"]),
        "bruno": Graph(graph.conn, graph.bus, default_owner=bruno["owner_id"]),
        "charlie": Graph(graph.conn, graph.bus, default_owner=charlie["owner_id"]),
        "ana_id": ana["account_id"],
        "bruno_id": bruno["account_id"],
        "charlie_id": charlie["account_id"],
    }


# ---- 1. Bulletin Security (Cross-Account) ----------------------------------

def test_bulletin_cross_account_security(world):
    ana, bruno, charlie = world["ana"], world["bruno"], world["charlie"]
    ana_id, bruno_id, charlie_id = world["ana_id"], world["bruno_id"], world["charlie_id"]

    # Ana creates a private crew and invites Bruno
    crew = crews.create(ana, "Private climbing", topic="climbing", city="Lisbon",
                        visibility="private", admission="approval", admin_id=ana_id)
    crew_id = crew["id"]

    crews.invite(ana, crew_id, bruno_id, by=ana_id)
    crews.accept_invite(bruno, crew_id, bruno_id)

    # Ana publishes a bulletin
    bulletin_id = bulletin.publish_bulletin(ana, crew_id, "Trip Cancelled", "Due to rain", caller_id=ana_id)
    assert bulletin_id is not None

    # Bruno can list the bulletins and see it
    bulletins = bulletin.list_bulletins(bruno, crew_id, caller_id=bruno_id)
    assert len(bulletins) == 1
    assert bulletins[0]["title"] == "Trip Cancelled"

    # Charlie (stranger) cannot publish a bulletin
    with pytest.raises(ValueError, match="access denied"):
        bulletin.publish_bulletin(charlie, crew_id, "Forged Announcement", "Spam", caller_id=charlie_id)

    # Charlie cannot list bulletins
    with pytest.raises(ValueError, match="access denied"):
        bulletin.list_bulletins(charlie, crew_id, caller_id=charlie_id)


# ---- 2. Chatroom Security (Cross-Account) ----------------------------------

def test_chatroom_cross_account_security(world):
    ana, bruno, charlie = world["ana"], world["bruno"], world["charlie"]
    ana_id, bruno_id, charlie_id = world["ana_id"], world["bruno_id"], world["charlie_id"]

    # Ana creates a public crew, Bruno joins
    crew = crews.create(ana, "Public Sushi", topic="sushi", city="Lisbon",
                        visibility="public", admission="open", admin_id=ana_id)
    crew_id = crew["id"]
    crews.request_join(bruno, crew_id, bruno_id)

    # Ana adds an event under the crew
    event_id = events_ingest.add_social_event(ana, "Sushi Outing", "2026-08-10T19:00:00Z", "Sushi place")
    
    # Update event to link to crew_id
    session = ana.session("convoy", {"*"})
    session.update_entity(event_id, {"crew_id": crew_id}, source="test")

    # Ana sends a chatroom message
    msg_id = chatroom.send_message(ana, event_id, "ana", "Who is coming?", caller_id=ana_id)
    assert msg_id is not None

    # Bruno can read it
    messages = chatroom.list_messages(bruno, event_id, caller_id=bruno_id)
    assert len(messages) == 1
    assert messages[0]["message"] == "Who is coming?"

    # Charlie cannot send a message to this chatroom
    with pytest.raises(ValueError, match="access denied"):
        chatroom.send_message(charlie, event_id, "charlie", "Hack!", caller_id=charlie_id)

    # Charlie cannot read this chatroom
    with pytest.raises(ValueError, match="access denied"):
        chatroom.list_messages(charlie, event_id, caller_id=charlie_id)


# ---- 3. Gallery & Collage Security (Cross-Account) ------------------------

def test_gallery_and_collage_cross_account_security(world):
    ana, bruno, charlie = world["ana"], world["bruno"], world["charlie"]
    ana_id, bruno_id, charlie_id = world["ana_id"], world["bruno_id"], world["charlie_id"]

    # Ana creates a crew, Bruno joins
    crew_id = crews.create(ana, "Photo Club", topic="photos", city="Lisbon", admin_id=ana_id)["id"]
    crews.invite(ana, crew_id, bruno_id, by=ana_id)
    crews.accept_invite(bruno, crew_id, bruno_id)


    # Add event under crew
    event_id = events_ingest.add_social_event(ana, "Photo walk", "2026-08-12T10:00:00Z")
    ana.session("convoy", {"*"}).update_entity(event_id, {"crew_id": crew_id}, source="test")

    # Ana uploads a photo
    photo_id = gallery.upload_photo(ana, event_id, ana_id, "https://walk.com/1.jpg", caller_id=ana_id)
    assert photo_id is not None

    # Bruno can list photos and create a collage
    photos = gallery.list_photos(bruno, event_id, caller_id=bruno_id)
    assert len(photos) == 1
    assert photos[0]["photo_url"] == "https://walk.com/1.jpg"

    photos_collage = collage.create_photo_collage(bruno, event_id, caller_id=bruno_id)
    assert len(photos_collage) == 1
    assert photos_collage[0]["url"] == "https://walk.com/1.jpg"

    # Charlie cannot upload
    with pytest.raises(ValueError, match="access denied"):
        gallery.upload_photo(charlie, event_id, charlie_id, "https://walk.com/hack.jpg", caller_id=charlie_id)

    # Charlie cannot list
    with pytest.raises(ValueError, match="access denied"):
        gallery.list_photos(charlie, event_id, caller_id=charlie_id)

    # Charlie cannot create collage
    with pytest.raises(ValueError, match="access denied"):
        collage.create_photo_collage(charlie, event_id, caller_id=charlie_id)


# ---- 4. Direct Messages Security (Isolation) -------------------------------

def test_direct_messages_security(world):
    ana, bruno, charlie = world["ana"], world["bruno"], world["charlie"]
    ana_id, bruno_id, charlie_id = world["ana_id"], world["bruno_id"], world["charlie_id"]

    # Ana sends a DM to Bruno
    msg = chat.send_message(ana, ana_id, bruno_id, "Hey Bruno", caller_id=ana_id)
    assert msg["message_id"] is not None

    # Bruno can fetch and see it
    msgs = chat.get_messages(bruno, bruno_id, caller_id=bruno_id)
    assert len(msgs) == 1
    assert msgs[0]["body"] == "Hey Bruno"

    # Ana can fetch and see it (querying as herself)
    msgs_ana = chat.get_messages(ana, ana_id, caller_id=ana_id)
    assert len(msgs_ana) == 1
    assert msgs_ana[0]["body"] == "Hey Bruno"

    # Charlie cannot send message impersonating Ana
    with pytest.raises(ValueError, match="access denied"):
        chat.send_message(charlie, ana_id, bruno_id, "Fake Ana", caller_id=charlie_id)

    # Charlie cannot fetch Ana or Bruno's messages
    with pytest.raises(ValueError, match="access denied"):
        chat.get_messages(charlie, bruno_id, caller_id=charlie_id)

    with pytest.raises(ValueError, match="access denied"):
        chat.get_messages(charlie, ana_id, caller_id=charlie_id)
