import tkinter as tk
from tkinter import messagebox
import math
import sqlite3
 
# ---------------------------------------------------------
# NOTE: This is a STANDALONE test file. It creates its own
# tiny throwaway database so you can test the layout without
# touching your real family_tree.db or your main app file.
# Once this looks good, we'll merge the relevant parts back
# into your actual project file.
# ---------------------------------------------------------
 
connection = sqlite3.connect(":memory:")  # temporary in-RAM database, resets every run
cursor = connection.cursor()
 
cursor.execute("""
    CREATE TABLE people (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT,
        last_name TEXT,
        birth_date TEXT,
        death_date TEXT,
        sex TEXT,
        notes TEXT
    )
""")
cursor.execute("""
    CREATE TABLE relationships (
        person_id INTEGER,
        related_person_id INTEGER,
        relationship_type TEXT
    )
""")
 
# a few test people so the tree isn't empty
test_people = [
    ("Alden", "Stormwind", "01.01.1400", "", "male", "Test note"),
    ("Mira", "Stormwind", "01.01.1402", "", "female", ""),
    ("Kael", "Stormwind", "01.01.1425", "", "male", ""),
    ("Lyra", "Stormwind", "01.01.1427", "", "female", ""),
]
for p in test_people:
    cursor.execute("INSERT INTO people (first_name, last_name, birth_date, death_date, sex, notes) VALUES (?, ?, ?, ?, ?, ?)", p)
connection.commit()
 
cursor.execute("INSERT INTO relationships VALUES (3, 1, 'parent')")
cursor.execute("INSERT INTO relationships VALUES (3, 2, 'parent')")
cursor.execute("INSERT INTO relationships VALUES (4, 1, 'parent')")
cursor.execute("INSERT INTO relationships VALUES (4, 2, 'parent')")
cursor.execute("INSERT INTO relationships VALUES (1, 2, 'spouse')")
connection.commit()
 
# ---------------------------------------------------------
# Globals used by the tree logic (same pattern as your app)
# ---------------------------------------------------------
tree_positions = {}
tree_zoom = 1.0
tree_pan_x = 0
tree_pan_y = 0
pan_start_x = 0
pan_start_y = 0


drag_threshold = 6  # pixels of wiggle room allowed before it counts as a drag
click_start_x = 0
click_start_y = 0

# --- Collapsible state ---
add_person_collapsed = False

ADD_PERSON_EXPANDED_HEIGHT = 420
ADD_PERSON_COLLAPSED_HEIGHT = 30  # just enough for the header bar

search_list_collapsed = False

SEARCH_LIST_HEADER_HEIGHT = 30


 
def calculate_generations():
    cursor.execute("SELECT id FROM people")
    all_ids = [row[0] for row in cursor.fetchall()]
 
    generations = {}
 
    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'parent'")
    parent_links = cursor.fetchall()
 
    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'spouse'")
    spouse_links = cursor.fetchall()
 
    if all_ids and not generations:
        generations[all_ids[0]] = 0
 
    changed = True
    while changed:
        changed = False
        for child_id, parent_id in parent_links:
            if child_id in generations and parent_id not in generations:
                generations[parent_id] = generations[child_id] - 1
                changed = True
            elif parent_id in generations and child_id not in generations:
                generations[child_id] = generations[parent_id] + 1
                changed = True
        for person_a, person_b in spouse_links:
            if person_a in generations and person_b not in generations:
                generations[person_b] = generations[person_a]
                changed = True
            elif person_b in generations and person_a not in generations:
                generations[person_a] = generations[person_b]
                changed = True
 
    for person_id in all_ids:
        if person_id not in generations:
            generations[person_id] = 0
 
    return generations
 
 
def calculate_positions():
    generations = calculate_generations()
 
    cursor.execute("SELECT DISTINCT person_id FROM relationships UNION SELECT DISTINCT related_person_id FROM relationships")
    connected_ids = {row[0] for row in cursor.fetchall()}
 
    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'spouse'")
    spouse_links = cursor.fetchall()
    spouse_of = {}
    for a, b in spouse_links:
        spouse_of[a] = b
        spouse_of[b] = a
 
    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'parent'")
    parent_links = cursor.fetchall()
    parents_of = {}
    for child_id, parent_id in parent_links:
        parents_of.setdefault(child_id, []).append(parent_id)
 
    people_by_generation = {}
    unconnected_ids = []
 
    for person_id, gen in generations.items():
        if person_id in connected_ids:
            people_by_generation.setdefault(gen, []).append(person_id)
        else:
            unconnected_ids.append(person_id)
 
    positions = {}
    horizontal_spacing = 150
    vertical_spacing = 150
 
    sorted_gens = sorted(people_by_generation.keys())
 
    for gen in sorted_gens:
        person_ids = people_by_generation[gen]
 
        units = []
        seen = set()
        for person_id in person_ids:
            if person_id in seen:
                continue
            unit = [person_id]
            seen.add(person_id)
            partner = spouse_of.get(person_id)
            if partner in person_ids and partner not in seen:
                unit.append(partner)
                seen.add(partner)
            units.append(unit)
 
        unit_targets = []
        for unit in units:
            parent_xs = []
            for member in unit:
                for parent_id in parents_of.get(member, []):
                    if parent_id in positions:
                        parent_xs.append(positions[parent_id][0])
            target_x = sum(parent_xs) / len(parent_xs) if parent_xs else None
            unit_targets.append(target_x)
 
        with_target = [(unit_targets[i], i) for i in range(len(units)) if unit_targets[i] is not None]
        without_target = [i for i in range(len(units)) if unit_targets[i] is None]
        with_target.sort()
        order = [i for _, i in with_target] + without_target
 
        next_free_x = 100
        for i in order:
            unit = units[i]
            target_x = unit_targets[i]
            desired_x = target_x if target_x is not None else next_free_x
            start_x = max(desired_x, next_free_x)
            for offset, member in enumerate(unit):
                x = start_x + offset * horizontal_spacing
                y = gen * vertical_spacing + 300
                positions[member] = (x, y)
            next_free_x = start_x + len(unit) * horizontal_spacing
 
    for index, person_id in enumerate(unconnected_ids):
        x = index * horizontal_spacing + 100
        y = 700
        positions[person_id] = (x, y)
 
    return positions
 
 
def get_screen_position(person_id):
    logical_x, logical_y = tree_positions[person_id]
    screen_x = logical_x * tree_zoom + tree_pan_x
    screen_y = logical_y * tree_zoom + tree_pan_y
    return screen_x, screen_y
 
 
def draw_tree():
    canvas.delete("all")
 
    radius = 40 * tree_zoom
 
    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'parent'")
    parent_links = cursor.fetchall()
    for child_id, parent_id in parent_links:
        if child_id in tree_positions and parent_id in tree_positions:
            x1, y1 = get_screen_position(parent_id)
            x2, y2 = get_screen_position(child_id)
            canvas.create_line(x1, y1, x2, y2, fill="black", width=2)
 
    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'spouse'")
    spouse_links = cursor.fetchall()
    for person_id, spouse_id in spouse_links:
        if person_id in tree_positions and spouse_id in tree_positions:
            x1, y1 = get_screen_position(person_id)
            x2, y2 = get_screen_position(spouse_id)
            canvas.create_line(x1, y1, x2, y2, fill="red", width=2, dash=(4, 2))
 
    cursor.execute("SELECT id, first_name, last_name, sex FROM people")
    people = cursor.fetchall()
 
    font_size = max(int(10 * tree_zoom), 6)
 
    for person_id, first_name, last_name, sex in people:
        x, y = get_screen_position(person_id)
        circle_color = "pink" if sex == "female" else "lightblue"
        canvas.create_oval(
            x - radius, y - radius,
            x + radius, y + radius,
            fill=circle_color, outline="black",
            tags=(f"person_{person_id}", "person_shape")
        )
        canvas.create_text(
            x, y, text=f"{first_name}\n{last_name}",
            font=("Arial", font_size),
            tags=(f"person_{person_id}", "person_shape")
        )
        canvas.tag_bind(f"person_{person_id}", "<Button-1>", lambda event, pid=person_id: open_radial_menu(canvas, pid))
 
 
def zoom(event):
    global tree_zoom, tree_pan_x, tree_pan_y
 
    factor = 1.1 if event.delta > 0 else 0.9
    new_zoom = tree_zoom * factor
 
    tree_pan_x = event.x - (event.x - tree_pan_x) * factor
    tree_pan_y = event.y - (event.y - tree_pan_y) * factor
    tree_zoom = new_zoom
 
    draw_tree()

 
def clear_radial_menu(canvas):
    canvas.delete("radial_menu")

 
def on_canvas_press(event):
    global pan_start_x, pan_start_y, click_start_x, click_start_y

    clicked_items = canvas.find_withtag("current")
    clicked_a_person = False
    if clicked_items:
        tags = canvas.gettags(clicked_items[0])
        if any(tag.startswith("person_") for tag in tags):
            clicked_a_person = True

    if not clicked_a_person:
        clear_radial_menu(canvas)

    pan_start_x = event.x - tree_pan_x
    pan_start_y = event.y - tree_pan_y
    click_start_x = event.x
    click_start_y = event.y


def do_pan(event):
    global tree_pan_x, tree_pan_y

    if abs(event.x - click_start_x) < drag_threshold and abs(event.y - click_start_y) < drag_threshold:
        return  # still within the click "wiggle room", don't pan yet

    tree_pan_x = event.x - pan_start_x
    tree_pan_y = event.y - pan_start_y
    draw_tree()
 
 
def refresh_tree():
    draw_tree()
 
 
def handle_radial_action(person_id, action):
    clear_radial_menu(canvas)
    if action == "delete":
        delete_person_from_tree(person_id)
    elif action == "view_details":
        print(f"(would open View Details for person {person_id})")
    else:
        print(f"Person {person_id}: {action} (not wired up in this test file)")
 
 
def open_radial_menu(canvas, person_id):
    clear_radial_menu(canvas)
 
    x, y = get_screen_position(person_id)
    outer_radius = 100 * tree_zoom
 
    labels = ["Add Spouse", "Add Parents", "View Details", "Deleting", "Settings", "Add Children"]
    actions = ["add_spouse", "add_parent", "view_details", "delete", "settings", "add_child"]
    angle_step = 360 / len(labels)
 
    for i in range(len(labels)):
        rotation_offset = -30
        start_angle = i * angle_step + rotation_offset
        tag = f"radial_{person_id}_{actions[i]}"
 
        canvas.create_arc(
            x - outer_radius, y - outer_radius,
            x + outer_radius, y + outer_radius,
            start=start_angle, extent=angle_step,
            fill="#eeeeee", outline="black",
            style=tk.PIESLICE,
            tags=("radial_menu", tag)
        )
 
        mid_angle = math.radians(start_angle + angle_step / 2)
        label_radius = outer_radius * 0.6
        label_x = x + label_radius * math.cos(mid_angle)
        label_y = y - label_radius * math.sin(mid_angle)
 
        canvas.create_text(
            label_x, label_y, text=labels[i],
            font=("Arial", max(6, int(8 * tree_zoom))), width=int(53 * tree_zoom),
            justify="center",
            tags=("radial_menu",)
        )
 
        canvas.tag_bind(tag, "<Button-1>", lambda event, pid=person_id, act=actions[i]: handle_radial_action(pid, act))
    canvas.tag_raise(f"person_{person_id}")
 
 
def delete_person_from_tree(person_id):
    cursor.execute("SELECT first_name, last_name FROM people WHERE id = ?", (person_id,))
    person = cursor.fetchone()
    confirmed = messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete {person[0]} {person[1]}?")
    if confirmed:
        cursor.execute("DELETE FROM relationships WHERE person_id = ? OR related_person_id = ?", (person_id, person_id))
        cursor.execute("DELETE FROM people WHERE id = ?", (person_id,))
        connection.commit()
        global tree_positions
        tree_positions = calculate_positions()
        refresh_tree()
 
 
def open_tree_view():
    global tree_positions, tree_zoom, tree_pan_x, tree_pan_y
 
    tree_positions = calculate_positions()
    xs = [pos[0] for pos in tree_positions.values()]
    if xs:
        tree_pan_x = 400 - (min(xs) + max(xs)) / 2
    else:
        tree_pan_x = 0

    canvas.bind("<MouseWheel>", zoom)
    canvas.bind("<ButtonPress-1>", on_canvas_press)
    canvas.bind("<B1-Motion>", do_pan)
 
    draw_tree()
 

def toggle_add_person():
    global add_person_collapsed
    add_person_collapsed = not add_person_collapsed

    if add_person_collapsed:
        add_person_content.pack_forget()
        add_person_frame.place(x=10, y=10, width=260, height=ADD_PERSON_COLLAPSED_HEIGHT)
        toggle_add_person_btn.config(text="▼")
    else:
        add_person_frame.place(x=10, y=10, width=260, height=ADD_PERSON_EXPANDED_HEIGHT)
        add_person_content.pack(fill="both", expand=True)
        toggle_add_person_btn.config(text="▲")

    resize_search_list_frame()


def toggle_search_list():
    global search_list_collapsed
    search_list_collapsed = not search_list_collapsed

    if search_list_collapsed:
        search_list_content.pack_forget()
        toggle_search_list_btn.config(text="▼")
    else:
        search_list_content.pack(fill="both", expand=True)
        toggle_search_list_btn.config(text="▲")

    resize_search_list_frame()


def resize_search_list_frame():
    current_height = ADD_PERSON_COLLAPSED_HEIGHT if add_person_collapsed else ADD_PERSON_EXPANDED_HEIGHT
    new_y = 10 + current_height + 10

    if search_list_collapsed:
        search_list_frame.place(x=10, y=new_y, width=260, relheight=0, height=SEARCH_LIST_HEADER_HEIGHT)
    else:
        search_list_frame.place(x=10, y=new_y, width=260, relheight=1, height=-(new_y + 10))





# ---------------------------------------------------------
# The skeleton (from last step) + the canvas now driven by
# the real tree logic above
# ---------------------------------------------------------
window = tk.Tk()
window.title("Family Tree")
window.state("zoomed")
 
# --- Bottom layer: the tree canvas, fills the ENTIRE window ---
canvas = tk.Canvas(window, bg="white")
canvas.place(x=0, y=0, relwidth=1, relheight=1)
 
# --- Floating panels on top, positioned with .place() ---
 
title_frame = tk.Frame(window, bg="#dddddd", bd=2, relief="solid")
title_frame.place(relx=0.5, y=10, anchor="n", width=350, height=50)
tk.Label(title_frame, text="Family Tree Name", font=("Arial", 14, "bold"), bg="#dddddd").pack(expand=True)
 
add_person_frame = tk.Frame(window, bg="#eeeeee", bd=2, relief="solid")
add_person_frame.place(x=10, y=10, width=260, height=ADD_PERSON_EXPANDED_HEIGHT)

add_person_header = tk.Frame(add_person_frame, bg="#dddddd")
add_person_header.pack(fill="x")
tk.Label(add_person_header, text="Add new Person", bg="#dddddd", font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=4)
toggle_add_person_btn = tk.Button(add_person_header, text="▲", width=2, command=toggle_add_person)
toggle_add_person_btn.pack(side="right", padx=4)

tk.Label(add_person_frame, text="First name").pack(anchor="w", padx=8)
first_name_entry = tk.Entry(add_person_frame)
first_name_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_frame, text="Last name").pack(anchor="w", padx=8)
last_name_entry = tk.Entry(add_person_frame)
last_name_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_frame, text="Birth date (DD.MM.YYYY)").pack(anchor="w", padx=8)
birth_date_entry = tk.Entry(add_person_frame)
birth_date_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_frame, text="Death date (DD.MM.YYYY)").pack(anchor="w", padx=8)
death_date_entry = tk.Entry(add_person_frame)
death_date_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_frame, text="Sex (male/female/other)").pack(anchor="w", padx=8)
sex_entry = tk.Entry(add_person_frame)
sex_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_frame, text="Notes").pack(anchor="w", padx=8)
notes_entry = tk.Entry(add_person_frame)
notes_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Button(add_person_frame, text="Save Person", command=save_person).pack(pady=8)
 
search_list_frame = tk.Frame(window, bg="#eeeeee", bd=2, relief="solid")

search_list_header = tk.Frame(search_list_frame, bg="#dddddd")
search_list_header.pack(fill="x")
tk.Label(search_list_header, text="All Characters", bg="#dddddd", font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=4)
toggle_search_list_btn = tk.Button(search_list_header, text="▲", width=2, command=toggle_search_list)
toggle_search_list_btn.pack(side="right", padx=4)

search_list_content = tk.Frame(search_list_frame, bg="#eeeeee")
search_list_content.pack(fill="both", expand=True)
tk.Label(search_list_content, text="Searchbar", bg="#eeeeee").pack(anchor="w", padx=8, pady=8)
 
info_frame = tk.Frame(window, bg="#eeeeee", bd=2, relief="solid")
info_frame.place(relx=1.0, x=-390, y=10, width=380, relheight=1, height=-20)
tk.Label(info_frame, text="All Informations", bg="#eeeeee", font=("Arial", 10, "bold")).pack(anchor="w", padx=8, pady=8)
 
# --- Start the tree, now that the canvas exists ---
open_tree_view()
resize_search_list_frame()
 
window.mainloop()
 