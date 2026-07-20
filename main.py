import os
import time
import datetime
import aiohttp
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TORN_API_KEY = os.getenv("TORN_API_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

BASE_URL = "https://api.torn.com/v2"

import csv
import json

# Output paths resolved relative to this script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(SCRIPT_DIR, "oc_delays.csv")
TRACKING_JSON_PATH = os.path.join(SCRIPT_DIR, "delayed_tracking.json")
DELAY_BUFFER = 60 # seconds
SCRIPT_START_TIME = time.time()

# Setup Discord intents (Members intent is required to read server nicknames)
intents = discord.Intents.default()
intents.members = True 
client = discord.Client(intents=intents)

# Dictionary to track notified OCs and their ready_at timestamp
notified_ocs = {}

def load_delayed_tracking():
    if not os.path.exists(TRACKING_JSON_PATH):
        return {}
    try:
        with open(TRACKING_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading delayed tracking: {e}")
        return {}

def save_delayed_tracking(data):
    try:
        with open(TRACKING_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving delayed tracking: {e}")

def get_logged_crime_ids():
    if not os.path.exists(CSV_PATH):
        return set()
    logged_ids = set()
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None) # Skip header
            for row in reader:
                if row:
                    logged_ids.add(row[0].strip())
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return logged_ids

def log_delayed_oc_to_csv(crime_id, expected_ready, executed_at, delaying_members_str):
    file_exists = os.path.exists(CSV_PATH)
    try:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "OC ID",
                    "Expected Ready Time (Timestamp)",
                    "Expected Ready Time (UTC)",
                    "Executed Time (Timestamp)",
                    "Executed Time (UTC)",
                    "Delaying Faction Member(s)"
                ])
            
            ready_utc = datetime.datetime.fromtimestamp(expected_ready, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S TCT')
            executed_utc = datetime.datetime.fromtimestamp(executed_at, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S TCT')
            
            writer.writerow([
                str(crime_id),
                str(expected_ready),
                ready_utc,
                str(executed_at),
                executed_utc,
                delaying_members_str
            ])
            print(f"Logged delayed OC {crime_id} to CSV.")
    except Exception as e:
        print(f"Error writing to CSV: {e}")

async def get_completed_ocs(session):
    """Fetch faction's completed OCs."""
    print("Fetching completed OCs...")
    url = f"{BASE_URL}/faction/crimes/?cat=completed"
    params = {"key": TORN_API_KEY, "sort": "DESC"}
    
    try:
        async with session.get(url, headers=get_headers(), params=params) as response:
            response.raise_for_status()
            data = await response.json()
            
            if "crimes" in data:
                return data["crimes"]
            elif "faction" in data and "crimes" in data["faction"]:
                return data["faction"]["crimes"]
            else:
                if isinstance(data, list):
                    return data
                return list(data.values()) if isinstance(data, dict) and not "error" in data else []
    except Exception as e:
        print(f"Error fetching completed OCs: {e}")
        return []

def get_headers():
    return {"Authorization": f"ApiKey {TORN_API_KEY}"}

async def get_planning_ocs(session):
    """Fetch faction's OCs currently in the planning state."""
    print("Fetching planned OCs...")
    url = f"{BASE_URL}/faction/crimes/?cat=planning"
    params = {"key": TORN_API_KEY}
    
    try:
        async with session.get(url, headers=get_headers(), params=params) as response:
            response.raise_for_status()
            data = await response.json()
            
            if "crimes" in data:
                return data["crimes"]
            elif "faction" in data and "crimes" in data["faction"]:
                return data["faction"]["crimes"]
            else:
                if isinstance(data, list):
                    return data
                return list(data.values()) if isinstance(data, dict) and not "error" in data else []
    except Exception as e:
        print(f"Error fetching OCs: {e}")
        return []

async def get_user_details(session, user_id, default_name):
    """Fetch user's profile to get formatted name and status description."""
    url = f"{BASE_URL}/user/{user_id}/profile/?cat=all"
    params = {"key": TORN_API_KEY}
    
    try:
        async with session.get(url, headers=get_headers(), params=params) as response:
            response.raise_for_status()
            data = await response.json()
            
            profile = data.get("profile") or data
            
            name = profile.get("name", default_name)
            fetched_id = profile.get("player_id") or profile.get("id") or user_id
            
            formatted_name = f"{name} [{fetched_id}]"
            
            status_info = profile.get("status", {})
            state = status_info.get("state", "Okay")
            description = status_info.get("description", "")
            if not description:
                description = state
                
            return formatted_name, description, state
            
    except Exception as e:
        print(f"Error fetching details for {user_id}: {e}")
        return f"{default_name} [{user_id}]", "Error fetching status", "Error"

async def get_item_name(session, item_id):
    """Fetch item name from Torn API."""
    url = f"{BASE_URL}/torn/{item_id}/items"
    params = {"key": TORN_API_KEY}
    
    try:
        async with session.get(url, headers=get_headers(), params=params) as response:
            response.raise_for_status()
            data = await response.json()
            
            items = data.get("items")
            if isinstance(items, list) and len(items) > 0:
                return items[0].get("name", f"Item ID {item_id}")
                
            if "name" in data:
                return data.get("name")
                
            return f"Item ID {item_id}"
            
    except Exception as e:
        print(f"Error fetching item name for {item_id}: {e}")
        return f"Item ID {item_id}"

def find_member_by_torn_id(guild, torn_id):
    """Search for a member whose display_name contains the torn ID in brackets."""
    target_str = f"[{torn_id}]"
    for member in guild.members:
        # Check if the exact target like '[3740237]' is in the display name
        if target_str in member.display_name:
            return member
    return None

@tasks.loop(minutes=5)
async def poll_ocs():
    """
    Runs every 5 minutes.
    - Fetches all planning OCs and checks member statuses.
    - Records any delaying members (with their exact reason) into delayed_tracking.json.
    - Processes newly completed OCs and logs delayed ones to oc_delays.csv.
    Discord notifications are NOT sent here — that is handled by notify_ocs().
    """
    print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] Polling OCs (5-min)...")

    if not TORN_API_KEY:
        return

    async with aiohttp.ClientSession() as session:
        ocs = await get_planning_ocs(session)

        current_time = time.time()
        delayed_tracking = load_delayed_tracking()
        any_tracking_updated = False

        for oc in ocs:
            ready_at = None
            if isinstance(oc, dict):
                ready_at = oc.get("ready_at") or oc.get("time_ready")

            if not ready_at:
                continue

            # Only care about OCs that are currently delayed (past their ready time)
            if current_time <= ready_at:
                continue

            crime_name = oc.get("name", "Unknown Crime")
            crime_id = oc.get("id") or f"{crime_name}_{ready_at}"
            crime_id_str = str(crime_id)

            # Initialise tracking entry if not already present
            if crime_id_str not in delayed_tracking:
                delayed_tracking[crime_id_str] = {
                    "ready_at": ready_at,
                    "delaying_members": {}
                }
                any_tracking_updated = True

            # Build participants list from slots or participants field
            participants = []
            required_items = []

            slots = oc.get("slots") or oc.get("Slots")
            if slots:
                slots_iter = slots.values() if isinstance(slots, dict) else slots
                for slot in slots_iter:
                    if isinstance(slot, dict):
                        user = slot.get("user") or slot.get("User")
                        if user:
                            participants.append(user)

                        item_req = slot.get("item_requirement")
                        if item_req and isinstance(item_req, dict):
                            item_id = item_req.get("id") or item_req.get("item_id")
                            if item_id:
                                is_available = item_req.get("is_available", False)
                                user_id = user.get("id") or user.get("user_id") if isinstance(user, dict) else None
                                required_items.append({
                                    "item_id": item_id,
                                    "is_available": is_available,
                                    "user_id": user_id
                                })
            else:
                p_data = oc.get("participants", [])
                if isinstance(p_data, dict):
                    for u_id, p_info in p_data.items():
                        if isinstance(p_info, dict):
                            p_info['id'] = u_id
                            participants.append(p_info)
                        else:
                            participants.append({'id': u_id, 'name': str(p_info)})
                else:
                    participants = p_data

            # Build user -> required item mapping
            user_req_items = {}
            for req in required_items:
                user_req_items[str(req["user_id"])] = req

            # Cache item names
            item_names_cache = {}
            for req in required_items:
                item_id = req["item_id"]
                if item_id not in item_names_cache:
                    item_names_cache[item_id] = await get_item_name(session, item_id)

            for participant in participants:
                user_id = participant.get("id") or participant.get("user_id")
                fallback_name = participant.get("name", "Unknown User")

                if not user_id:
                    continue

                formatted_name, status_desc, state = await get_user_details(session, user_id, fallback_name)

                # Check required item availability
                user_id_str = str(user_id)
                if user_id_str in user_req_items:
                    req = user_req_items[user_id_str]
                    item_id = req["item_id"]
                    item_name = item_names_cache.get(item_id, f"Item ID {item_id}")
                    is_available = req["is_available"]
                    availability = "✅" if is_available else "❌"
                    status_desc += f"\nReq: {item_name} {availability}"
                    if not is_available:
                        state = "Missing Item"

                if state != "Okay":
                    clean_status = status_desc.replace("**", "").replace("\n", ", ")
                    reason = f"{state} ({clean_status})"
                    delayed_tracking[crime_id_str]["delaying_members"][str(user_id)] = {
                        "name": formatted_name,
                        "reason": reason
                    }
                    any_tracking_updated = True

        if any_tracking_updated:
            save_delayed_tracking(delayed_tracking)

        # Process completed crimes and write delayed ones to CSV
        try:
            completed_ocs = await get_completed_ocs(session)
            if completed_ocs:
                logged_ids = get_logged_crime_ids()
                delayed_tracking = load_delayed_tracking()
                tracking_changed = False

                for completed_oc in completed_ocs:
                    comp_id = completed_oc.get("id")
                    if not comp_id:
                        continue

                    comp_id_str = str(comp_id)

                    # Skip if already logged
                    if comp_id_str in logged_ids:
                        if comp_id_str in delayed_tracking:
                            del delayed_tracking[comp_id_str]
                            tracking_changed = True
                        continue

                    comp_ready = completed_oc.get("ready_at") or completed_oc.get("time_ready")
                    comp_executed = completed_oc.get("executed_at") or completed_oc.get("time_executed")

                    if not comp_ready or not comp_executed:
                        continue

                    # Only log OCs executed after the script started (ignore historical data)
                    if comp_executed < SCRIPT_START_TIME:
                        continue

                    # Log if delayed beyond the buffer
                    if comp_executed - comp_ready > DELAY_BUFFER:
                        delaying_members_list = []
                        if comp_id_str in delayed_tracking:
                            tracked_members = delayed_tracking[comp_id_str].get("delaying_members", {})
                            for uid, member_info in tracked_members.items():
                                m_name = member_info.get("name", "Unknown Member")
                                m_reason = member_info.get("reason", "Not Okay")
                                delaying_members_list.append(f"{m_name} ({m_reason})")

                        if not delaying_members_list:
                            delaying_members_str = "None (Leader Delay / Ready but not initiated)"
                        else:
                            delaying_members_str = "; ".join(delaying_members_list)

                        log_delayed_oc_to_csv(comp_id, comp_ready, comp_executed, delaying_members_str)
                        logged_ids.add(comp_id_str)

                    # Prune from tracking JSON once processed
                    if comp_id_str in delayed_tracking:
                        del delayed_tracking[comp_id_str]
                        tracking_changed = True

                if tracking_changed:
                    save_delayed_tracking(delayed_tracking)
        except Exception as e:
            print(f"Error processing completed OCs: {e}")


@tasks.loop(hours=1)
async def notify_ocs():
    """
    Runs every hour.
    - Fetches all planning OCs and checks member statuses.
    - Sends Discord alerts for any OC within the notification window.
    Data gathering and CSV logging are handled separately by poll_ocs().
    """
    print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] Running hourly Discord notify check...")

    if not TORN_API_KEY:
        print("Error: TORN_API_KEY is missing.")
        return

    if not DISCORD_CHANNEL_ID:
        print("Error: DISCORD_CHANNEL_ID is missing.")
        return

    channel = client.get_channel(int(DISCORD_CHANNEL_ID))
    if not channel:
        print(f"Error: Could not find Discord Channel ID {DISCORD_CHANNEL_ID}. Ensure the bot is invited to the server and the ID is correct.")
        return

    async with aiohttp.ClientSession() as session:
        ocs = await get_planning_ocs(session)
        if not ocs:
            print("No planned OCs found or error occurred.")
            return

        current_time = time.time()
        alert_window = 3.5 * 3600

        # Prune stale OC notification records (older than 24 hours)
        stale_threshold = current_time - (24 * 3600)
        keys_to_remove = [k for k, v in notified_ocs.items() if v < stale_threshold]
        for k in keys_to_remove:
            del notified_ocs[k]

        for oc in ocs:
            ready_at = None
            if isinstance(oc, dict):
                ready_at = oc.get("ready_at") or oc.get("time_ready")

            if not ready_at:
                continue

            time_until_ready = ready_at - current_time

            # Only notify within the window: up to 3.5h before ready, or up to 10h after ready
            if not (-28800 <= time_until_ready <= alert_window):
                continue

            crime_name = oc.get("name", "Unknown Crime")
            ready_dt = datetime.datetime.fromtimestamp(ready_at, datetime.timezone.utc)
            ready_time_str = ready_dt.strftime('%Y-%m-%d %H:%M:%S TCT')
            oc_id = f"{crime_name}_{ready_at}"

            fields = []
            mentions = []
            participants = []
            required_items = []

            slots = oc.get("slots") or oc.get("Slots")
            if slots:
                slots_iter = slots.values() if isinstance(slots, dict) else slots
                for slot in slots_iter:
                    if isinstance(slot, dict):
                        user = slot.get("user") or slot.get("User")
                        if user:
                            participants.append(user)

                        item_req = slot.get("item_requirement")
                        if item_req and isinstance(item_req, dict):
                            item_id = item_req.get("id") or item_req.get("item_id")
                            if item_id:
                                is_available = item_req.get("is_available", False)
                                user_id = user.get("id") or user.get("user_id") if isinstance(user, dict) else None
                                required_items.append({
                                    "item_id": item_id,
                                    "is_available": is_available,
                                    "user_id": user_id
                                })
            else:
                p_data = oc.get("participants", [])
                if isinstance(p_data, dict):
                    for u_id, p_info in p_data.items():
                        if isinstance(p_info, dict):
                            p_info['id'] = u_id
                            participants.append(p_info)
                        else:
                            participants.append({'id': u_id, 'name': str(p_info)})
                else:
                    participants = p_data

            user_req_items = {}
            for req in required_items:
                user_req_items[str(req["user_id"])] = req

            item_names_cache = {}
            for req in required_items:
                item_id = req["item_id"]
                if item_id not in item_names_cache:
                    item_names_cache[item_id] = await get_item_name(session, item_id)

            all_okay = True

            for participant in participants:
                user_id = participant.get("id") or participant.get("user_id")
                fallback_name = participant.get("name", "Unknown User")

                if user_id:
                    formatted_name, status_desc, state = await get_user_details(session, user_id, fallback_name)

                    user_id_str = str(user_id)
                    if user_id_str in user_req_items:
                        req = user_req_items[user_id_str]
                        item_id = req["item_id"]
                        item_name = item_names_cache.get(item_id, f"Item ID {item_id}")
                        is_available = req["is_available"]
                        availability = "✅" if is_available else "❌"
                        status_desc += f"\n**Req:** {item_name} {availability}"
                        if not is_available:
                            state = "Missing Item"

                    if state != "Okay":
                        all_okay = False
                        should_ping = True
                        if state == "Traveling" and "to torn" in status_desc.lower():
                            should_ping = False
                        if should_ping:
                            member = find_member_by_torn_id(channel.guild, user_id)
                            if member and member.mention not in mentions:
                                mentions.append(member.mention)
                else:
                    formatted_name = fallback_name
                    status_desc = "Unknown ID"
                    all_okay = False

                fields.append({
                    "name": formatted_name,
                    "value": status_desc,
                    "inline": True
                })

            if oc_id in notified_ocs and all_okay:
                print(f"Skipping {crime_name} - already notified and all users are okay.")
                continue

            notified_ocs[oc_id] = ready_at

            embed_color = discord.Color.green() if all_okay else discord.Color.red()
            embed = discord.Embed(
                title=f"🐢 Ready Soon: {crime_name}",
                description=f"**Time until ready:** {time_until_ready / 3600:.1f} hours\n**Ready at:** {ready_time_str}",
                color=embed_color
            )

            for field in fields:
                embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])

            embed.set_footer(text="Torn City OC Notifier")
            content_text = " ".join(mentions) if mentions else ""

            try:
                await channel.send(content=content_text, embed=embed)
                print(f"Sent notification for {crime_name}")
            except Exception as e:
                print(f"Failed to send Discord message: {e}")


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Bot is connected and ready.")

    if not poll_ocs.is_running():
        print("Starting 5-minute OC polling loop...")
        poll_ocs.start()

    if not notify_ocs.is_running():
        print("Starting hourly Discord notification loop...")
        notify_ocs.start()

def main():
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN is missing from environment variables.")
        return

    print("Starting Discord Bot...")
    # This call blocks and runs the bot event loop
    client.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()
