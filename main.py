import sqlite3
import tkinter as tk
from tkinter import messagebox
import math

connection = sqlite3.connect("family_tree.db")
cursor = connection.cursor()

last_view_position = None
last_tree_geometry = None
current_tree_window = None
tree_zoom = 1.0
tree_pan_x = 0
tree_pan_y = 0
tree_canvas = None
tree_positions = {}
pan_start_x = 0
pan_start_y = 0

drag_threshold = 5  # pixels of wiggle room before it counts as a real drag

add_person_collapsed = False
ADD_PERSON_EXPANDED_HEIGHT = 420
ADD_PERSON_COLLAPSED_HEIGHT = 30

search_list_collapsed = False
SEARCH_LIST_HEADER_HEIGHT = 30

current_info_person_id = None

cursor.execute("""
    CREATE TABLE IF NOT EXISTS people (
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
    CREATE TABLE IF NOT EXISTS relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        related_person_id INTEGER,
        relationship_type TEXT,
        FOREIGN KEY (person_id) REFERENCES people (id),
        FOREIGN KEY (related_person_id) REFERENCES people (id)
    )
""")

connection.commit()

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

def save_window_position():
    with open("window_position.txt", "w") as file:
        file.write(window.geometry())

def load_window_position():
    try:
        with open("window_position.txt", "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        return None
    
def add_person(first_name, last_name, birth_date, death_date, sex, notes):
    cursor.execute("""
        INSERT INTO people (first_name, last_name, birth_date, death_date, sex, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (first_name, last_name, birth_date, death_date, sex, notes))
    connection.commit()
    print(f"Added {first_name} {last_name} successfully!")

def delete_person(person_id, view_window):
    global last_view_position
    last_view_position = view_window.geometry()
    cursor.execute("DELETE FROM people WHERE id = ?", (person_id,))
    connection.commit()
    view_window.destroy()
    view_people()

def save_person():
    add_person(
        first_name_entry.get(),
        last_name_entry.get(),
        birth_date_entry.get(),
        death_date_entry.get(),
        sex_entry.get(),
        notes_entry.get()
    )
    first_name_entry.delete(0, tk.END)
    last_name_entry.delete(0, tk.END)
    birth_date_entry.delete(0, tk.END)
    death_date_entry.delete(0, tk.END)
    sex_entry.delete(0, tk.END)
    notes_entry.delete(0, tk.END)

def toggle_parent(person_id, parent_id, var):
    if var.get():
        cursor.execute("""
            INSERT INTO relationships (person_id, related_person_id, relationship_type)
            VALUES (?, ?, ?)
        """, (person_id, parent_id, "parent"))
    else:
        cursor.execute("""
            DELETE FROM relationships
            WHERE person_id = ? AND related_person_id = ? AND relationship_type = 'parent'
        """, (person_id, parent_id))
    connection.commit()

def toggle_spouse(person_id, spouse_id, var):
    if var.get():
        cursor.execute("""
            INSERT INTO relationships (person_id, related_person_id, relationship_type)
            VALUES (?, ?, ?)
        """, (person_id, spouse_id, "spouse"))
    else:
        cursor.execute("""
            DELETE FROM relationships
            WHERE person_id = ? AND related_person_id = ? AND relationship_type = 'spouse'
        """, (person_id, spouse_id))
    connection.commit()

def view_people():
    view_window = tk.Toplevel(window)
    open_near_main(view_window)
    view_window.title("All People")

    if last_view_position:
        view_window.geometry(last_view_position)

    cursor.execute("SELECT id, first_name, last_name, birth_date, death_date, sex, notes FROM people")
    people = cursor.fetchall()

    headers = ["ID", "First Name", "Last Name", "Birth", "Death", "Sex", "Notes"]
    for column_index, header in enumerate(headers):
        tk.Label(view_window, text=header, font=("Arial", 10, "bold")).grid(row=0, column=column_index)

    for row_index, person in enumerate(people, start=1):
        for column_index, value in enumerate(person):
            tk.Label(view_window, text=value).grid(row=row_index, column=column_index, padx=5)

        person_id = person[0]

        tk.Button(
                    view_window,
                    text="Edit",
                    command=lambda pid=person_id: open_edit_window(pid, view_window)
                ).grid(row=row_index, column=len(headers))

        tk.Button(
                    view_window,
                    text="Delete",
                    command=lambda pid=person_id, win=view_window: delete_person(pid, win)
                ).grid(row=row_index, column=len(headers) + 1)
        
        cursor.execute("SELECT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'parent'", (person_id,))
        current_parent_ids = [row[0] for row in cursor.fetchall()]

        parent_menu_button = tk.Menubutton(view_window, text="Parents", relief="raised")
        parent_menu = tk.Menu(parent_menu_button, tearoff=0)
        parent_menu_button.configure(menu=parent_menu)

        cursor.execute("SELECT id, first_name, last_name FROM people WHERE id != ?", (person_id,))
        other_people = cursor.fetchall()

        for other_id, other_first, other_last in other_people:
            var = tk.BooleanVar(value=(other_id in current_parent_ids))
            parent_menu.add_checkbutton(
                label=f"{other_first} {other_last}",
                variable=var,
                command=lambda pid=person_id, oid=other_id, v=var: toggle_parent(pid, oid, v)
            )

        parent_menu_button.grid(row=row_index, column=len(headers) + 2)

        cursor.execute("SELECT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'spouse'", (person_id,))
        current_spouse_ids = [row[0] for row in cursor.fetchall()]

        spouse_menu_button = tk.Menubutton(view_window, text="Spouse", relief="raised")
        spouse_menu = tk.Menu(spouse_menu_button, tearoff=0)
        spouse_menu_button.configure(menu=spouse_menu)

        for other_id, other_first, other_last in other_people:
            var = tk.BooleanVar(value=(other_id in current_spouse_ids))
            spouse_menu.add_checkbutton(
                label=f"{other_first} {other_last}",
                variable=var,
                command=lambda pid=person_id, oid=other_id, v=var: toggle_spouse(pid, oid, v)
            )

        spouse_menu_button.grid(row=row_index, column=len(headers) + 3)

def update_info_panel(person_id):
    global current_info_person_id
    current_info_person_id = person_id

    cursor.execute("SELECT first_name, last_name, birth_date, death_date, sex, notes FROM people WHERE id = ?", (person_id,))
    result = cursor.fetchone()
    if not result:
        return
    first_name, last_name, birth_date, death_date, sex, notes = result

    info_frame.place(relx=1.0, x=-390, y=10, width=380, relheight=1, height=-20)

    info_name_label.config(text=f"{first_name} {last_name}")
    info_born_label.config(text=f"Born: {birth_date or '—'}")
    info_died_label.config(text=f"Died: {death_date or '—'}")
    info_sex_label.config(text=f"Sex: {sex or '—'}")
    info_notes_label.config(text=notes or "—")

def clear_info_panel():
    global current_info_person_id
    current_info_person_id = None
    info_frame.place_forget()

def open_edit_window(person_id, view_window):
    cursor.execute("SELECT first_name, last_name, birth_date, death_date, sex, notes FROM people WHERE id = ?", (person_id,))
    person = cursor.fetchone()

    edit_window = tk.Toplevel(window)
    open_near_main(edit_window)
    edit_window.title("Edit Person")

    labels = ["First name", "Last name", "Birth date (DD.MM.YYYY)", "Death date (DD.MM.YYYY)", "Sex (male/female/other)", "Notes"]
    entries = []

    for row_index, label_text in enumerate(labels):
        tk.Label(edit_window, text=label_text).grid(row=row_index, column=0)
        entry = tk.Entry(edit_window)
        entry.insert(0, person[row_index])
        entry.grid(row=row_index, column=1)
        entries.append(entry)

    def save_edit():
        updated_values = [entry.get() for entry in entries]
        cursor.execute("""
            UPDATE people
            SET first_name = ?, last_name = ?, birth_date = ?, death_date = ?, sex = ?, notes = ?
            WHERE id = ?
        """, (*updated_values, person_id))
        connection.commit()
        edit_window.destroy()
        view_window.destroy()
        view_people()

    tk.Button(edit_window, text="Save Changes", command=save_edit).grid(row=len(labels), column=0, columnspan=2)

def open_near_main(new_window):
    x = window.winfo_x()
    y = window.winfo_y()
    new_window.geometry(f"+{x + 50}+{y + 50}")

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

def focus_on_person(person_id):
    global tree_pan_x, tree_pan_y

    if person_id not in tree_positions:
        return

    logical_x, logical_y = tree_positions[person_id]

    canvas_width = canvas.winfo_width()
    canvas_height = canvas.winfo_height()

    tree_pan_x = (canvas_width / 2) - (logical_x * tree_zoom)
    tree_pan_y = (canvas_height / 2) - (logical_y * tree_zoom)

    draw_tree()
    open_radial_menu(canvas, person_id)
    update_info_panel(person_id)

def refresh_sidebar_list(filter_text=""):
    for widget in sidebar_list_inner.winfo_children():
        widget.destroy()

    cursor.execute("SELECT id, first_name, last_name FROM people ORDER BY first_name")
    people = cursor.fetchall()

    filter_text = filter_text.strip().lower()

    for person_id, first_name, last_name in people:
        full_name = f"{first_name} {last_name}"
        if filter_text and filter_text not in full_name.lower():
            continue

        row = tk.Label(
            sidebar_list_inner, text=full_name, bg="white",
            anchor="w", padx=8, pady=4, cursor="hand2"
        )
        row.pack(fill="x")
        row.bind("<Button-1>", lambda event, pid=person_id: focus_on_person(pid))

def on_search_typed(event):
    refresh_sidebar_list(search_entry.get())

def open_tree_view():
    global tree_positions, tree_zoom, tree_pan_x, tree_pan_y

    tree_positions = calculate_positions()
    center_tree()

    canvas.bind("<MouseWheel>", zoom)
    canvas.bind("<ButtonPress-1>", on_canvas_press)
    canvas.bind("<B1-Motion>", do_pan)

    draw_tree()

def center_tree():
    global tree_pan_x, tree_pan_y

    if not tree_positions:
        tree_pan_x = 0
        tree_pan_y = 0
        return

    xs = [pos[0] for pos in tree_positions.values()]
    ys = [pos[1] for pos in tree_positions.values()]
    mid_x = (min(xs) + max(xs)) / 2
    mid_y = (min(ys) + max(ys)) / 2

    canvas.update_idletasks()  # forces Tkinter to calculate real window size before we read it
    canvas_width = canvas.winfo_width()
    canvas_height = canvas.winfo_height()

    tree_pan_x = (canvas_width / 2) - (mid_x * tree_zoom)
    tree_pan_y = (canvas_height / 2) - (mid_y * tree_zoom)

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
        clear_info_panel()

    pan_start_x = event.x - tree_pan_x
    pan_start_y = event.y - tree_pan_y
    click_start_x = event.x
    click_start_y = event.y

def get_screen_position(person_id):
    logical_x, logical_y = tree_positions[person_id]
    screen_x = logical_x * tree_zoom + tree_pan_x
    screen_y = logical_y * tree_zoom + tree_pan_y
    return screen_x, screen_y

def draw_tree():
    canvas.delete("all")

    radius = 40 * tree_zoom

    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'spouse'")
    spouse_links = cursor.fetchall()

    drawn_spouse_pairs = set()
    for person_id, spouse_id in spouse_links:
        pair = frozenset((person_id, spouse_id))
        if pair in drawn_spouse_pairs:
            continue
        drawn_spouse_pairs.add(pair)
        if person_id in tree_positions and spouse_id in tree_positions:
            x1, y1 = get_screen_position(person_id)
            x2, y2 = get_screen_position(spouse_id)
            canvas.create_line(x1, y1, x2, y2, fill="#d17b7b", width=2, dash=(4, 2))

    cursor.execute("SELECT person_id, related_person_id FROM relationships WHERE relationship_type = 'parent'")
    parent_links = cursor.fetchall()

    parents_of = {}
    for child_id, parent_id in parent_links:
        parents_of.setdefault(child_id, set()).add(parent_id)

    children_of_couple = {}
    for child_id, parent_ids in parents_of.items():
        couple_key = frozenset(parent_ids)
        children_of_couple.setdefault(couple_key, []).append(child_id)

    for couple_key, children in children_of_couple.items():
        parent_positions = [get_screen_position(pid) for pid in couple_key if pid in tree_positions]
        if not parent_positions:
            continue

        anchor_x = sum(p[0] for p in parent_positions) / len(parent_positions)
        anchor_y = sum(p[1] for p in parent_positions) / len(parent_positions)

        child_positions = [(cid, get_screen_position(cid)) for cid in children if cid in tree_positions]
        if not child_positions:
            continue

        bus_y = anchor_y + (child_positions[0][1][1] - anchor_y) / 2

        line_color = "#8a8a8a"
        line_width = 2

        for cid, (cx, cy) in child_positions:
            points = [
                anchor_x, anchor_y,
                anchor_x, bus_y,
                cx, bus_y,
                cx, cy
            ]
            canvas.create_line(
                *points,
                fill=line_color, width=line_width,
                capstyle="round", smooth=True, splinesteps=12
            )

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

def do_pan(event):
    global tree_pan_x, tree_pan_y

    if abs(event.x - click_start_x) < drag_threshold and abs(event.y - click_start_y) < drag_threshold:
        return  # still just a click, not an intentional drag

    tree_pan_x = event.x - pan_start_x
    tree_pan_y = event.y - pan_start_y
    draw_tree()

def refresh_tree():
    draw_tree()
    refresh_sidebar_list(search_entry.get())

def handle_radial_action(person_id, action):
    clear_radial_menu(canvas)
    if action == "add_child":
        open_add_child_window(person_id)
    elif action == "add_parent":
        open_add_parent_window(person_id)
    elif action == "add_spouse":
        open_add_spouse_window(person_id)
    elif action == "delete":
        delete_person_from_tree(person_id)
    elif action == "view_details":
        open_view_details_window(person_id)
    else:
        print(f"Person {person_id}: {action}")

def open_radial_menu(canvas, person_id):
    clear_radial_menu(canvas)
    update_info_panel(person_id)

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
            font=("Arial", max(6, int(8 * tree_zoom))), width=int(55 * tree_zoom),
            justify="center",
            tags=("radial_menu",)
        )

        canvas.tag_bind(tag, "<Button-1>", lambda event, pid=person_id, act=actions[i]: handle_radial_action(pid, act))
    canvas.tag_raise(f"person_{person_id}")

def clear_radial_menu(canvas):
    canvas.delete("radial_menu")

def open_add_spouse_window(person_id):
    add_window = tk.Toplevel(window)
    add_window.title("Add Spouse")
    open_near_main(add_window)

    tk.Label(add_window, text="Link an existing person:", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2)

    cursor.execute("SELECT id, first_name, last_name FROM people WHERE id != ?", (person_id,))
    other_people = cursor.fetchall()
    options = [f"{p[0]} - {p[1]} {p[2]}" for p in other_people]

    selected_option = tk.StringVar()
    if options:
        selected_option.set(options[0])
        dropdown = tk.OptionMenu(add_window, selected_option, *options)
        dropdown.grid(row=1, column=0)

        def link_existing():
            spouse_id = int(selected_option.get().split(" - ")[0])
            cursor.execute("""
                INSERT INTO relationships (person_id, related_person_id, relationship_type)
                VALUES (?, ?, ?)
            """, (person_id, spouse_id, "spouse"))
            connection.commit()
            add_window.destroy()
            refresh_tree()

        tk.Button(add_window, text="Link", command=link_existing).grid(row=1, column=1)

    tk.Label(add_window, text="Current spouses:", font=("Arial", 10, "bold")).grid(row=2, column=0, columnspan=2)

    cursor.execute("SELECT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'spouse'", (person_id,))
    current_spouse_ids = [row[0] for row in cursor.fetchall()]

    current_row = 3
    for other_id, other_first, other_last in other_people:
        if other_id in current_spouse_ids:
            tk.Label(add_window, text=f"{other_first} {other_last}").grid(row=current_row, column=0)

            def make_unlink(spouse_id):
                def unlink():
                    cursor.execute("""
                        DELETE FROM relationships
                        WHERE person_id = ? AND related_person_id = ? AND relationship_type = 'spouse'
                    """, (person_id, spouse_id))
                    connection.commit()
                    add_window.destroy()
                    refresh_tree()
                return unlink

            tk.Button(add_window, text="Unlink", command=make_unlink(other_id)).grid(row=current_row, column=1)
            current_row += 1

    if not current_spouse_ids:
        tk.Label(add_window, text="(none yet)").grid(row=current_row, column=0, columnspan=2)
        current_row += 1

    tk.Label(add_window, text="— or —").grid(row=current_row, column=0, columnspan=2)
    tk.Label(add_window, text="Create a new person:", font=("Arial", 10, "bold")).grid(row=current_row + 1, column=0, columnspan=2)

    labels = ["First name", "Last name", "Birth date (DD.MM.YYYY)", "Death date (DD.MM.YYYY)", "Sex (male/female/other)", "Notes"]
    entries = []

    for i, label_text in enumerate(labels):
        row = current_row + 2 + i
        tk.Label(add_window, text=label_text).grid(row=row, column=0)
        entry = tk.Entry(add_window)
        entry.grid(row=row, column=1)
        entries.append(entry)

    def save_new_spouse():
        values = [entry.get() for entry in entries]
        cursor.execute("""
            INSERT INTO people (first_name, last_name, birth_date, death_date, sex, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, tuple(values))
        new_spouse_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO relationships (person_id, related_person_id, relationship_type)
            VALUES (?, ?, ?)
        """, (person_id, new_spouse_id, "spouse"))
        connection.commit()
        add_window.destroy()
        refresh_tree()

    tk.Button(add_window, text="Save New Person", command=save_new_spouse).grid(row=current_row + 2 + len(labels), column=0, columnspan=2)

def open_add_parent_window(child_id):
    add_window = tk.Toplevel(window)
    add_window.title("Add Parent")
    open_near_main(add_window)

    tk.Label(add_window, text="Current parents:", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2)

    cursor.execute("SELECT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'parent'", (child_id,))
    current_parent_ids = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT id, first_name, last_name FROM people WHERE id != ?", (child_id,))
    other_people = cursor.fetchall()

    current_row = 1
    for other_id, other_first, other_last in other_people:
        if other_id in current_parent_ids:
            tk.Label(add_window, text=f"{other_first} {other_last}").grid(row=current_row, column=0)

            def make_unlink(parent_id):
                def unlink():
                    cursor.execute("""
                        DELETE FROM relationships
                        WHERE person_id = ? AND related_person_id = ? AND relationship_type = 'parent'
                    """, (child_id, parent_id))
                    connection.commit()
                    add_window.destroy()
                    refresh_tree()
                return unlink

            tk.Button(add_window, text="Unlink", command=make_unlink(other_id)).grid(row=current_row, column=1)
            current_row += 1

    if not current_parent_ids:
        tk.Label(add_window, text="(none yet)").grid(row=current_row, column=0, columnspan=2)
        current_row += 1

    tk.Label(add_window, text="Link an existing person:", font=("Arial", 10, "bold")).grid(row=current_row, column=0, columnspan=2)
    current_row += 1

    options = [f"{p[0]} - {p[1]} {p[2]}" for p in other_people]
    selected_option = tk.StringVar()

    if options:
        selected_option.set(options[0])
        dropdown = tk.OptionMenu(add_window, selected_option, *options)
        dropdown.grid(row=current_row, column=0)

        def link_existing():
            parent_id = int(selected_option.get().split(" - ")[0])
            cursor.execute("""
                INSERT INTO relationships (person_id, related_person_id, relationship_type)
                VALUES (?, ?, ?)
            """, (child_id, parent_id, "parent"))
            connection.commit()
            add_window.destroy()
            refresh_tree()

        tk.Button(add_window, text="Link", command=link_existing).grid(row=current_row, column=1)
        current_row += 1

    tk.Label(add_window, text="— or —").grid(row=current_row, column=0, columnspan=2)
    current_row += 1
    tk.Label(add_window, text="Create a new person:", font=("Arial", 10, "bold")).grid(row=current_row, column=0, columnspan=2)
    current_row += 1

    labels = ["First name", "Last name", "Birth date (DD.MM.YYYY)", "Death date (DD.MM.YYYY)", "Sex (male/female/other)", "Notes"]
    entries = []

    for i, label_text in enumerate(labels):
        row = current_row + i
        tk.Label(add_window, text=label_text).grid(row=row, column=0)
        entry = tk.Entry(add_window)
        entry.grid(row=row, column=1)
        entries.append(entry)

    def save_new_parent():
        values = [entry.get() for entry in entries]
        cursor.execute("""
            INSERT INTO people (first_name, last_name, birth_date, death_date, sex, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, tuple(values))
        new_parent_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO relationships (person_id, related_person_id, relationship_type)
            VALUES (?, ?, ?)
        """, (child_id, new_parent_id, "parent"))
        connection.commit()
        add_window.destroy()
        refresh_tree()

    tk.Button(add_window, text="Save New Person", command=save_new_parent).grid(row=current_row + len(labels), column=0, columnspan=2)

def open_view_details_window(person_id):
    cursor.execute("SELECT first_name, last_name, birth_date, death_date, sex, notes FROM people WHERE id = ?", (person_id,))
    first_name, last_name, birth_date, death_date, sex, notes = cursor.fetchone()

    details_window = tk.Toplevel(window)
    details_window.title(f"{first_name} {last_name}")
    open_near_main(details_window)
    details_window.geometry("300x250")

    details_window.configure(bg="#cecece")

    tk.Label(details_window, text=f"{first_name} {last_name}", font=("Arial", 14, "bold"), bg="#cecece").pack(pady=(15, 10))
    tk.Label(details_window, text=f"Born: {birth_date or '—'}", bg="#cecece").pack(anchor="w", padx=20)
    tk.Label(details_window, text=f"Died: {death_date or '—'}", bg="#cecece").pack(anchor="w", padx=20)
    tk.Label(details_window, text=f"Sex: {sex or '—'}", bg="#cecece").pack(anchor="w", padx=20)
    tk.Label(details_window, text="Notes:", font=("Arial", 10, "bold"), bg="#cecece").pack(anchor="w", padx=20, pady=(15, 0))
    tk.Label(details_window, text=notes or "—", wraplength=250, justify="left", bg="#cecece").pack(anchor="w", padx=20)

def delete_person_from_tree(person_id):
    cursor.execute("SELECT first_name, last_name FROM people WHERE id = ?", (person_id,))
    person = cursor.fetchone()
    confirmed = messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete {person[0]} {person[1]}?")
    if confirmed:
        cursor.execute("DELETE FROM relationships WHERE person_id = ? OR related_person_id = ?", (person_id, person_id))
        cursor.execute("DELETE FROM people WHERE id = ?", (person_id,))
        connection.commit()
        refresh_tree()

def open_add_child_window(parent_id):
    add_window = tk.Toplevel(window)
    add_window.title("Add Child")
    open_near_main(add_window)

    tk.Label(add_window, text="Current children:", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2)

    cursor.execute("SELECT person_id FROM relationships WHERE related_person_id = ? AND relationship_type = 'parent'", (parent_id,))
    current_child_ids = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT id, first_name, last_name FROM people WHERE id != ?", (parent_id,))
    other_people = cursor.fetchall()

    current_row = 1
    for other_id, other_first, other_last in other_people:
        if other_id in current_child_ids:
            tk.Label(add_window, text=f"{other_first} {other_last}").grid(row=current_row, column=0)

            def make_unlink(child_id):
                def unlink():
                    cursor.execute("""
                        DELETE FROM relationships
                        WHERE person_id = ? AND related_person_id = ? AND relationship_type = 'parent'
                    """, (child_id, parent_id))
                    connection.commit()
                    add_window.destroy()
                    refresh_tree()
                return unlink

            tk.Button(add_window, text="Unlink", command=make_unlink(other_id)).grid(row=current_row, column=1)
            current_row += 1

    if not current_child_ids:
        tk.Label(add_window, text="(none yet)").grid(row=current_row, column=0, columnspan=2)
        current_row += 1

    tk.Label(add_window, text="Link an existing person:", font=("Arial", 10, "bold")).grid(row=current_row, column=0, columnspan=2)
    current_row += 1

    options = [f"{p[0]} - {p[1]} {p[2]}" for p in other_people]
    selected_option = tk.StringVar()

    if options:
        selected_option.set(options[0])
        dropdown = tk.OptionMenu(add_window, selected_option, *options)
        dropdown.grid(row=current_row, column=0)

        def link_existing():
            child_id = int(selected_option.get().split(" - ")[0])
            cursor.execute("""
                INSERT INTO relationships (person_id, related_person_id, relationship_type)
                VALUES (?, ?, ?)
            """, (child_id, parent_id, "parent"))
            connection.commit()
            add_window.destroy()
            refresh_tree()

        tk.Button(add_window, text="Link", command=link_existing).grid(row=current_row, column=1)
        current_row += 1

    tk.Label(add_window, text="— or —").grid(row=current_row, column=0, columnspan=2)
    current_row += 1
    tk.Label(add_window, text="Create a new person:", font=("Arial", 10, "bold")).grid(row=current_row, column=0, columnspan=2)
    current_row += 1

    labels = ["First name", "Last name", "Birth date (DD.MM.YYYY)", "Death date (DD.MM.YYYY)", "Sex (male/female/other)", "Notes"]
    entries = []

    for i, label_text in enumerate(labels):
        row = current_row + i
        tk.Label(add_window, text=label_text).grid(row=row, column=0)
        entry = tk.Entry(add_window)
        entry.grid(row=row, column=1)
        entries.append(entry)

    def save_new_child():
        values = [entry.get() for entry in entries]
        cursor.execute("""
            INSERT INTO people (first_name, last_name, birth_date, death_date, sex, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, tuple(values))
        new_child_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO relationships (person_id, related_person_id, relationship_type)
            VALUES (?, ?, ?)
        """, (new_child_id, parent_id, "parent"))
        connection.commit()
        add_window.destroy()
        refresh_tree()

    tk.Button(add_window, text="Save New Person", command=save_new_child).grid(row=current_row + len(labels), column=0, columnspan=2)

def open_edit_window_from_tree(person_id):
    cursor.execute("SELECT first_name, last_name, birth_date, death_date, sex, notes FROM people WHERE id = ?", (person_id,))
    person = cursor.fetchone()

    edit_window = tk.Toplevel(window)
    open_near_main(edit_window)
    edit_window.title("Edit Person")

    labels = ["First name", "Last name", "Birth date (DD.MM.YYYY)", "Death date (DD.MM.YYYY)", "Sex (male/female/other)", "Notes"]
    entries = []

    for row_index, label_text in enumerate(labels):
        tk.Label(edit_window, text=label_text).grid(row=row_index, column=0)
        entry = tk.Entry(edit_window)
        entry.insert(0, person[row_index])
        entry.grid(row=row_index, column=1)
        entries.append(entry)

    def save_edit():
        updated_values = [entry.get() for entry in entries]
        cursor.execute("""
            UPDATE people
            SET first_name = ?, last_name = ?, birth_date = ?, death_date = ?, sex = ?, notes = ?
            WHERE id = ?
        """, (*updated_values, person_id))
        connection.commit()
        edit_window.destroy()
        refresh_tree()

    tk.Button(edit_window, text="Save Changes", command=save_edit).grid(row=len(labels), column=0, columnspan=2)

def pop_out_info():
    if current_info_person_id is None:
        return

    cursor.execute("SELECT first_name, last_name, birth_date, death_date, sex, notes FROM people WHERE id = ?", (current_info_person_id,))
    result = cursor.fetchone()
    if not result:
        return
    first_name, last_name, birth_date, death_date, sex, notes = result

    clear_info_panel()

    popout = tk.Toplevel(window)
    popout.attributes("-topmost", True)
    popout.title(f"{first_name} {last_name}")
    popout.configure(bg="#eeeeee")
    popout.minsize(300, 250)

    button_x = popout_button.winfo_rootx()
    button_y = popout_button.winfo_rooty()
    popout.geometry(f"300x250+{button_x - 310}+{button_y}")

    tk.Label(popout, text=f"{first_name} {last_name}", font=("Arial", 14, "bold"), bg="#eeeeee").pack(anchor="w", padx=12, pady=(12, 6))
    tk.Label(popout, text=f"Born: {birth_date or '—'}", bg="#eeeeee").pack(anchor="w", padx=12)
    tk.Label(popout, text=f"Died: {death_date or '—'}", bg="#eeeeee").pack(anchor="w", padx=12)
    tk.Label(popout, text=f"Sex: {sex or '—'}", bg="#eeeeee").pack(anchor="w", padx=12)
    tk.Label(popout, text="Notes:", font=("Arial", 10, "bold"), bg="#eeeeee").pack(anchor="w", padx=12, pady=(12, 0))
    tk.Label(popout, text=notes or "—", wraplength=350, justify="left", bg="#eeeeee").pack(anchor="w", padx=12, pady=(0, 12))

window = tk.Tk()
window.title("Family Tree")
window.state("zoomed")

canvas = tk.Canvas(window, bg="white")
canvas.place(x=0, y=0, relwidth=1, relheight=1)

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

add_person_content = tk.Frame(add_person_frame, bg="#eeeeee")
add_person_content.pack(fill="both", expand=True)

tk.Label(add_person_content, text="First name", bg="#eeeeee").pack(anchor="w", padx=8)
first_name_entry = tk.Entry(add_person_content)
first_name_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_content, text="Last name", bg="#eeeeee").pack(anchor="w", padx=8)
last_name_entry = tk.Entry(add_person_content)
last_name_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_content, text="Birth date (DD.MM.YYYY)", bg="#eeeeee").pack(anchor="w", padx=8)
birth_date_entry = tk.Entry(add_person_content)
birth_date_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_content, text="Death date (DD.MM.YYYY)", bg="#eeeeee").pack(anchor="w", padx=8)
death_date_entry = tk.Entry(add_person_content)
death_date_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_content, text="Sex (male/female/other)", bg="#eeeeee").pack(anchor="w", padx=8)
sex_entry = tk.Entry(add_person_content)
sex_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Label(add_person_content, text="Notes", bg="#eeeeee").pack(anchor="w", padx=8)
notes_entry = tk.Entry(add_person_content)
notes_entry.pack(fill="x", padx=8, pady=(0, 4))

tk.Button(add_person_content, text="Save Person", command=save_person).pack(pady=8)

search_list_frame = tk.Frame(window, bg="#eeeeee", bd=2, relief="solid")

search_list_header = tk.Frame(search_list_frame, bg="#dddddd")
search_list_header.pack(fill="x")
tk.Label(search_list_header, text="All Characters", bg="#dddddd", font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=4)
toggle_search_list_btn = tk.Button(search_list_header, text="▲", width=2, command=toggle_search_list)
toggle_search_list_btn.pack(side="right", padx=4)

search_list_content = tk.Frame(search_list_frame, bg="#eeeeee")
search_list_content.pack(fill="both", expand=True)

search_entry = tk.Entry(search_list_content)
search_entry.pack(fill="x", padx=8, pady=8)
search_entry.bind("<KeyRelease>", on_search_typed)

sidebar_canvas = tk.Canvas(search_list_content, bg="white", highlightthickness=0)
sidebar_scrollbar = tk.Scrollbar(search_list_content, orient="vertical", command=sidebar_canvas.yview)
sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)

sidebar_scrollbar.pack(side="right", fill="y")
sidebar_canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))

sidebar_list_inner = tk.Frame(sidebar_canvas, bg="white")
sidebar_canvas.create_window((0, 0), window=sidebar_list_inner, anchor="nw")

def on_sidebar_list_configure(event):
    sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))

sidebar_list_inner.bind("<Configure>", on_sidebar_list_configure)

info_frame = tk.Frame(window, bg="#eeeeee", bd=2, relief="solid")

info_header = tk.Frame(info_frame, bg="#dddddd")
info_header.pack(fill="x")
tk.Label(info_header, text="All Informations", bg="#dddddd", font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=4)
popout_button = tk.Button(info_header, text="⧉", width=2, command=pop_out_info)
popout_button.pack(side="right", padx=4)

info_name_label = tk.Label(info_frame, text="No one selected", bg="#eeeeee", font=("Arial", 14, "bold"))
info_name_label.pack(anchor="w", padx=12, pady=(12, 6))

info_born_label = tk.Label(info_frame, text="Born: —", bg="#eeeeee")
info_born_label.pack(anchor="w", padx=12)

info_died_label = tk.Label(info_frame, text="Died: —", bg="#eeeeee")
info_died_label.pack(anchor="w", padx=12)

info_sex_label = tk.Label(info_frame, text="Sex: —", bg="#eeeeee")
info_sex_label.pack(anchor="w", padx=12)

tk.Label(info_frame, text="Notes:", bg="#eeeeee", font=("Arial", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 0))
info_notes_label = tk.Label(info_frame, text="—", bg="#eeeeee", wraplength=350, justify="left")
info_notes_label.pack(anchor="w", padx=12)

window.update()
open_tree_view()
resize_search_list_frame()
refresh_sidebar_list()

window.mainloop()