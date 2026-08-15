import sqlite3
import tkinter as tk
import math

from tkinter import messagebox


connection = sqlite3.connect("family_tree.db")
connection.execute("PRAGMA foreign_keys = ON")
cursor = connection.cursor()


PRESET_COLORS = [
    "#e74c3c",  # Red
    "#e67e22",  # Orange
    "#f1c40f",  # Yellow
    "#2ecc71",  # Green
    "#1abc9c",  # Teal
    "#3498db",  # Blue
    "#9b59b6",  # Purple
    "#e84393",  # Pink
    "#7f8c8d",  # Gray
    "#2c3e50",  # Dark
]
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
drag_threshold = 5

add_person_collapsed = False
ADD_PERSON_EXPANDED_HEIGHT = 420
ADD_PERSON_COLLAPSED_HEIGHT = 30
MANAGE_TAGS_EXPANDED_HEIGHT = 300

search_list_collapsed = False
SEARCH_LIST_HEADER_HEIGHT = 30

manage_tags_collapsed = False
MANAGE_TAGS_HEADER_HEIGHT = 30

current_info_person_id = None
suppress_next_clear = False
tag_subwindow = None


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

cursor.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE COLLATE NOCASE,
        color TEXT DEFAULT '#808080'
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS person_tags (
        person_id INTEGER,
        tag_id INTEGER,
        PRIMARY KEY (person_id, tag_id),
        FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
        FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
    )
""")

connection.commit()


class ResizeGrip(tk.Label):
    def __init__(self, parent, target_window, **kwargs):
        super().__init__(parent, text="◢", cursor="bottom_right_corner", **kwargs)
        self.target_window = target_window
        self.bind("<Button-1>", self.start_resize)
        self.bind("<B1-Motion>", self.do_resize)

    def start_resize(self, event):
        self._start_x = event.x_root
        self._start_y = event.y_root
        self._start_w = self.target_window.winfo_width()
        self._start_h = self.target_window.winfo_height()

    def do_resize(self, event):
        dx = event.x_root - self._start_x
        dy = event.y_root - self._start_y
        new_w = max(200, self._start_w + dx)
        new_h = max(150, self._start_h + dy)
        self.target_window.geometry(f"{new_w}x{new_h}")

class TagChipInput(tk.Frame):
    """
    A reusable tag input widget: shows colored chips with an 'x' to unlink,
    plus a text entry with a case-insensitive autocomplete dropdown.
    Drop this into any window that needs tag editing for a person.
    """

    def __init__(self, parent, conn, person_id, **kwargs):
        super().__init__(parent, **kwargs)
        self.conn = conn
        self.person_id = person_id

        # Row of existing chips
        self.chip_frame = tk.Frame(self)
        self.chip_frame.pack(fill="x", pady=(0, 4))

        # Entry + dropdown for adding new tags
        self.entry_var = tk.StringVar()
        self.entry_var.trace_add("write", self.on_type)

        self.entry = tk.Entry(self, textvariable=self.entry_var)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", self.on_enter)

        self.dropdown = tk.Listbox(self, height=4)
        self.dropdown.bind("<<ListboxSelect>>", self.on_select_suggestion)
        # not packed yet — only shown when there are suggestions

        self.refresh_chips()

    def refresh_chips(self):
        for widget in self.chip_frame.winfo_children():
            widget.destroy()

        tags = get_tags_for_person(self.conn, self.person_id)
        for tag_id, name, color in tags:
            self.create_chip(tag_id, name, color)

    def create_chip(self, tag_id, name, color):
        text_color = get_contrasting_text_color(color)

        chip = tk.Frame(self.chip_frame, bg=color)
        chip.pack(side="left", padx=2, pady=2)

        label = tk.Label(
            chip, text=name, bg=color, fg=text_color,
            padx=6, pady=2
        )
        label.pack(side="left")

        remove_btn = tk.Label(
            chip, text="x", bg=color, fg=text_color,
            padx=4, cursor="hand2"
        )
        remove_btn.pack(side="left")
        remove_btn.bind("<Button-1>", lambda e, tid=tag_id: self.remove_tag(tid))

    def remove_tag(self, tag_id):
        remove_tag_from_person(self.conn, self.person_id, tag_id)
        self.refresh_chips()

    def on_type(self, *args):
        query = self.entry_var.get().strip()
        if not query:
            self.dropdown.pack_forget()
            return

        results = search_tags(self.conn, query)
        self.dropdown.delete(0, tk.END)

        if results:
            for tag_id, name, color in results:
                self.dropdown.insert(tk.END, name)
            self._dropdown_results = results
            self.dropdown.pack(fill="x")
        else:
            self.dropdown.pack_forget()

    def on_select_suggestion(self, event):
        selection = self.dropdown.curselection()
        if not selection:
            return
        tag_id, name, color = self._dropdown_results[selection[0]]
        self.add_and_clear(tag_id)

    def on_enter(self, event):
        name = self.entry_var.get().strip()
        if not name:
            return

        # remove leading # if the user typed it
        if name.startswith("#"):
            name = name[1:]

        # assign a color: reuse if new tag matches an existing one, else pick next preset
        existing = search_tags(self.conn, name)
        exact_match = next((t for t in existing if t[1].lower() == name.lower()), None)

        if exact_match:
            tag_id = exact_match[0]
        else:
            color = PRESET_COLORS[len(existing) % len(PRESET_COLORS)]
            tag_id = get_or_create_tag(self.conn, name, color)

        self.add_and_clear(tag_id)

    def add_and_clear(self, tag_id):
        add_tag_to_person(self.conn, self.person_id, tag_id)
        self.entry_var.set("")
        self.dropdown.pack_forget()
        self.refresh_chips()

class TagFlowView(tk.Frame):
    """
    Read-only-ish tag display: chips flow left-to-right, wrapping to a new row
    when they run out of horizontal space. Scrolls after max_rows rows.
    Each chip has an 'x' to unlink it from the person.
    """

    def __init__(self, parent, conn, person_id, max_rows=4, row_height=28, on_change=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.conn = conn
        self.person_id = person_id
        self.max_rows = max_rows
        self.row_height = row_height
        self.on_change = on_change
        self.chip_widgets = []

        self.canvas = tk.Canvas(self, height=row_height * max_rows, highlightthickness=0, bg="#eeeeee")
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg="#eeeeee")
        self.inner_window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self.on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        self.refresh()

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_canvas_resize(self, event):
        self.canvas.itemconfig(self.inner_window_id, width=event.width)
        self.reflow()

    def refresh(self):
        for widget in self.inner.winfo_children():
            widget.destroy()

        tags = get_tags_for_person(self.conn, self.person_id)
        self.chip_widgets = [self.make_chip(tag_id, name, color) for tag_id, name, color in tags]
        self.reflow()

    def make_chip(self, tag_id, name, color):
        text_color = get_contrasting_text_color(color)
        chip = tk.Frame(self.inner, bg=color)

        tk.Label(chip, text=name, bg=color, fg=text_color, padx=6, pady=2).pack(side="left")

        remove_btn = tk.Label(chip, text="x", bg=color, fg=text_color, padx=4, cursor="hand2")
        remove_btn.pack(side="left")
        remove_btn.bind("<Button-1>", lambda e, tid=tag_id: self.remove_tag(tid))

        return chip

    def remove_tag(self, tag_id):
        remove_tag_from_person(self.conn, self.person_id, tag_id)
        self.refresh()
        if self.on_change:
            self.on_change()

    def reflow(self):
        width = self.canvas.winfo_width()
        if width <= 1:
            self.after(50, self.reflow)
            return

        x = 0
        y = 0
        row_height = 0
        spacing = 4

        for chip in self.chip_widgets:
            chip.update_idletasks()
            chip_w = chip.winfo_reqwidth()
            chip_h = chip.winfo_reqheight()

            if x + chip_w > width and x > 0:
                x = 0
                y += row_height + spacing
                row_height = 0

            chip.place(x=x, y=y)
            x += chip_w + spacing
            row_height = max(row_height, chip_h)

        total_height = y + row_height
        self.inner.config(height=total_height)
        self.canvas.configure(scrollregion=(0, 0, width, total_height))


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

def toggle_manage_tags():
    global manage_tags_collapsed
    manage_tags_collapsed = not manage_tags_collapsed

    if manage_tags_collapsed:
        manage_tags_content.pack_forget()
        toggle_manage_tags_btn.config(text="▼")
    else:
        manage_tags_content.pack(fill="both", expand=True)
        toggle_manage_tags_btn.config(text="▲")

    resize_search_list_frame()

def resize_search_list_frame():
    add_person_height = ADD_PERSON_COLLAPSED_HEIGHT if add_person_collapsed else ADD_PERSON_EXPANDED_HEIGHT
    manage_tags_y = 10 + add_person_height + 10

    if manage_tags_collapsed:
        manage_tags_frame.place(x=10, y=manage_tags_y, width=260, relheight=0, height=MANAGE_TAGS_HEADER_HEIGHT)
        manage_tags_height = MANAGE_TAGS_HEADER_HEIGHT
    else:
        manage_tags_frame.place(x=10, y=manage_tags_y, width=260, relheight=0, height=MANAGE_TAGS_EXPANDED_HEIGHT)
        manage_tags_height = MANAGE_TAGS_EXPANDED_HEIGHT

    search_list_y = manage_tags_y + manage_tags_height + 10

    if search_list_collapsed:
        search_list_frame.place(x=10, y=search_list_y, width=260, relheight=0, height=SEARCH_LIST_HEADER_HEIGHT)
    else:
        search_list_frame.place(x=10, y=search_list_y, width=260, relheight=1, height=-(search_list_y + 10))

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

def save_person():
    global tree_positions

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

    tree_positions = calculate_positions()
    draw_tree()
    refresh_sidebar_list(search_entry.get())

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

    refresh_info_tags()

    info_notes_text.delete("1.0", tk.END)
    info_notes_text.insert("1.0", notes or "")

def clear_info_panel():
    global current_info_person_id
    current_info_person_id = None
    info_frame.place_forget()

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
    global pan_start_x, pan_start_y, click_start_x, click_start_y, suppress_next_clear

    if suppress_next_clear:
        suppress_next_clear = False
    else:
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
            justify="center",
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
    global tree_positions
    tree_positions = calculate_positions()
    draw_tree()
    refresh_sidebar_list(search_entry.get())

def handle_radial_action(person_id, action):
    global suppress_next_clear
    suppress_next_clear = True
    clear_radial_menu(canvas)
    if action == "add_child":
        open_add_child_window(person_id)
    elif action == "add_parent":
        open_add_parent_window(person_id)
    elif action == "add_spouse":
        open_add_spouse_window(person_id)
    elif action == "delete":
        delete_person_from_tree(person_id)
    elif action == "edit":
        open_edit_window_from_tree(person_id)
    elif action == "link":
        x, y = get_screen_position(person_id)
        open_link_window(person_id, x, y)
    else:
        print(f"Person {person_id}: {action}")

def open_radial_menu(canvas, person_id):
    clear_radial_menu(canvas)
    update_info_panel(person_id)

    x, y = get_screen_position(person_id)
    outer_radius = 100 * tree_zoom

    labels = ["Add Spouse", "Add Parents", "Edit", "Deleting", "Link Unlink", "Add Children"]
    actions = ["add_spouse", "add_parent", "edit", "delete", "link", "add_child"]
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
            font=("Arial", max(6, int(8 * tree_zoom))), width=int(45 * tree_zoom),
            justify="center",
            tags=("radial_menu", tag)
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
            if len(get_parent_ids(child_id)) >= 2:
                messagebox.showinfo("Limit reached", "A person can only have 2 linked parents.")
                return

            parent_id = int(selected_option.get().split(" - ")[0])
            cursor.execute("""
                INSERT INTO relationships (person_id, related_person_id, relationship_type)
                VALUES (?, ?, ?)
            """, (child_id, parent_id, "parent"))
            connection.commit()
            auto_link_spouses_if_needed(child_id, parent_id)
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
        if len(get_parent_ids(child_id)) >= 2:
            messagebox.showinfo("Limit reached", "A person can only have 2 linked parents.")
            return

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
        auto_link_spouses_if_needed(child_id, new_parent_id)
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
    edit_window.attributes("-topmost", True)
    open_near_main(edit_window)
    edit_window.title(f"Edit Person – {person[0]} {person[1]}")

    edit_window.grid_columnconfigure(1, weight=1)
    edit_window.grid_columnconfigure(2, weight=0, minsize=10)

    labels = ["First name", "Last name", "Birth date (DD.MM.YYYY)", "Death date (DD.MM.YYYY)", "Sex (male/female/other)", "Notes"]
    entries = []

    for row_index, label_text in enumerate(labels):
        tk.Label(edit_window, text=label_text).grid(row=row_index, column=0)
        entry = tk.Entry(edit_window)
        entry.insert(0, person[row_index])
        entry.grid(row=row_index, column=1, sticky="ew", padx=(5, 8), pady=3)
        entries.append(entry)

    tag_input = TagChipInput(edit_window, connection, person_id)
    tag_input.grid(row=len(labels), column=0, columnspan=2, sticky="ew", pady=10)

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

    tk.Button(edit_window, text="Save Changes", command=save_edit).grid(row=len(labels) + 1, column=0, columnspan=2, pady=10)

    grip = ResizeGrip(edit_window, edit_window)
    grip.place(relx=1.0, rely=1.0, anchor="se")

def open_link_window(person_id, x=None, y=None):
    link_window = tk.Toplevel(window)
    link_window.attributes("-topmost", True)
    link_window.title(f"Link/Unlink — {get_person_name(person_id)}")

    if x is not None and y is not None:
        abs_x = canvas.winfo_rootx() + int(x) + 60
        abs_y = canvas.winfo_rooty() + int(y) - 100
        link_window.geometry(f"360x650+{abs_x}+{abs_y}")
    else:
        link_window.geometry("360x650")

    container = tk.Frame(link_window)
    container.pack(fill="both", expand=True, padx=10, pady=10)

    def build_section(title, get_current_ids, on_link, on_unlink):
        section = tk.LabelFrame(container, text=title, padx=6, pady=6)
        section.pack(fill="x", pady=(0, 10))

        current_list_frame = tk.Frame(section)
        current_list_frame.pack(fill="x")

        def refresh_current():
            for widget in current_list_frame.winfo_children():
                widget.destroy()
            current_ids = get_current_ids(person_id)
            if not current_ids:
                tk.Label(current_list_frame, text="(none yet)", fg="gray").pack(anchor="w")
            for other_id in current_ids:
                chip = tk.Frame(current_list_frame, bg="#e8e8e8", bd=1, relief="solid")
                chip.pack(fill="x", pady=2)

                tk.Label(chip, text=get_person_name(other_id), anchor="w", bg="#e8e8e8", padx=8, pady=4).pack(side="left", fill="x", expand=True)

                def do_unlink(oid=other_id):
                    link_window.attributes("-topmost", False)
                    confirmed = messagebox.askyesno("Unlink?", f"Unlink {get_person_name(oid)}?", parent=link_window)
                    link_window.attributes("-topmost", True)
                    if confirmed:
                        on_unlink(person_id, oid)
                        refresh_current()
                        refresh_results(search_entry_local.get())
                        refresh_tree()

                tk.Button(chip, text="x", width=2, bg="#e8e8e8", relief="flat", command=do_unlink).pack(side="right", padx=4, pady=2)

        search_row = tk.Frame(section)
        search_row.pack(fill="x", pady=(6, 0))

        sort_state = {"mode": "first"}

        def toggle_sort():
            sort_state["mode"] = "first" if sort_state["mode"] == "last" else "last"
            sort_btn.config(text="Sort: First" if sort_state["mode"] == "first" else "Sort: Last")
            refresh_results(search_entry_local.get())

        sort_btn = tk.Button(search_row, text="Sort: First", command=toggle_sort)
        sort_btn.pack(side="left")

        search_entry_local = tk.Entry(search_row)
        search_entry_local.pack(side="left", fill="x", expand=True, padx=4)

        show_all_state = {"expanded": False}

        def toggle_show_all():
            show_all_state["expanded"] = not show_all_state["expanded"]
            toggle_btn.config(text="▲" if show_all_state["expanded"] else "▼")
            refresh_results(search_entry_local.get())

        toggle_btn = tk.Button(search_row, text="▼", width=2, command=toggle_show_all)
        toggle_btn.pack(side="right")

        results_outer = tk.Frame(section)
        row_height = 24
        max_visible_rows = 6

        results_canvas = tk.Canvas(results_outer, height=row_height * max_visible_rows, highlightthickness=0)
        results_scrollbar = tk.Scrollbar(results_outer, orient="vertical", command=results_canvas.yview)
        results_canvas.configure(yscrollcommand=results_scrollbar.set)

        results_frame = tk.Frame(results_canvas)

        results_window_id = results_canvas.create_window((0, 0), window=results_frame, anchor="nw")

        def on_results_canvas_resize(event):
            results_canvas.itemconfig(results_window_id, width=event.width)

        results_canvas.bind("<Configure>", on_results_canvas_resize)

        def on_results_configure(event):
            results_canvas.configure(scrollregion=results_canvas.bbox("all"))

        results_frame.bind("<Configure>", on_results_configure)

        def on_results_mousewheel(event):
            results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        results_canvas.bind("<Enter>", lambda event: results_canvas.bind_all("<MouseWheel>", on_results_mousewheel))
        results_canvas.bind("<Leave>", lambda event: results_canvas.unbind_all("<MouseWheel>"))

        def refresh_results(filter_text=""):
            for widget in results_frame.winfo_children():
                widget.destroy()

            if not filter_text.strip() and not show_all_state["expanded"]:
                results_outer.pack_forget()
                return

            results_outer.pack(fill="x")
            results_canvas.pack(side="left", fill="both", expand=True)
            results_scrollbar.pack(side="right", fill="y")

            current_ids = get_current_ids(person_id)
            filter_text = filter_text.strip().lower()

            if sort_state["mode"] == "last":
                cursor.execute("""
                    SELECT id, first_name, last_name FROM people
                    WHERE id != ?
                    ORDER BY
                        CASE WHEN last_name IS NULL OR last_name = '' THEN 1 ELSE 0 END,
                        last_name,
                        first_name
                """, (person_id,))
            else:
                cursor.execute("""
                    SELECT id, first_name, last_name FROM people
                    WHERE id != ?
                    ORDER BY first_name
                """, (person_id,))

            for other_id, first, last in cursor.fetchall():
                if other_id in current_ids:
                    continue
                full_name = f"{first} {last}"
                if filter_text not in full_name.lower():
                    continue
                row = tk.Label(results_frame, text=full_name, anchor="w", cursor="hand2", bg="white")
                row.pack(fill="x", pady=1)

                def do_link(oid=other_id):
                    on_link(person_id, oid)
                    refresh_current()
                    refresh_results(search_entry_local.get())
                    refresh_tree()

                row.bind("<Button-1>", lambda event, f=do_link: f())

        search_entry_local.bind("<KeyRelease>", lambda event: refresh_results(search_entry_local.get()))

        refresh_current()
        refresh_results()

    build_section("Parents (max 2)", get_parent_ids, link_parent, unlink_parent)
    build_section("Children", get_child_ids, link_child, unlink_child)
    build_section("Spouses", get_spouse_ids, link_spouse, unlink_spouse)

def open_manage_tags_window():
    manage_window = tk.Toplevel(window)
    manage_window.attributes("-topmost", True)
    open_near_main(manage_window)
    manage_window.title("Manage Tags")

    manage_window.grid_columnconfigure(1, weight=1)

    list_frame = tk.Frame(manage_window)
    list_frame.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=10, pady=10)

    create_frame = tk.Frame(manage_window)
    create_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 10))

    tk.Label(create_frame, text="New tag name:").grid(row=0, column=0, sticky="w")
    new_tag_entry = tk.Entry(create_frame)
    new_tag_entry.grid(row=1, column=0, sticky="ew", pady=4)
    create_frame.grid_columnconfigure(0, weight=1)

    tk.Label(create_frame, text="Color:").grid(row=0, column=1, sticky="w", padx=(10, 0))
    color_swatch_frame = tk.Frame(create_frame)
    color_swatch_frame.grid(row=1, column=1, sticky="w", padx=(10, 0))

    selected_color = tk.StringVar(value=PRESET_COLORS[0])

    def select_color(color):
        selected_color.set(color)
        for swatch, c in swatch_widgets:
            swatch.config(relief="sunken" if c == color else "raised")

    swatch_widgets = []
    for i, color in enumerate(PRESET_COLORS):
        swatch = tk.Label(color_swatch_frame, bg=color, width=2, height=1, relief="raised", cursor="hand2")
        swatch.grid(row=0, column=i, padx=1)
        swatch.bind("<Button-1>", lambda e, c=color: select_color(c))
        swatch_widgets.append((swatch, color))

    select_color(PRESET_COLORS[0])

    def create_new_tag():
        name = new_tag_entry.get().strip()
        if name.startswith("#"):
            name = name[1:]
        if not name:
            return

        existing = search_tags(connection, name)
        exact_match = next((t for t in existing if t[1].lower() == name.lower()), None)

        if exact_match:
            messagebox.showinfo("Tag exists", f"{name} already exists.")
            return

        get_or_create_tag(connection, name, selected_color.get())
        new_tag_entry.delete(0, tk.END)
        refresh_tag_list()

    tk.Button(create_frame, text="Create Tag", command=create_new_tag).grid(row=1, column=2, padx=(10, 0))

    def refresh_tag_list():
        for widget in list_frame.winfo_children():
            widget.destroy()

        tags = get_all_tags(connection)

        for row_index, (tag_id, name, color, usage_count) in enumerate(tags):
            text_color = get_contrasting_text_color(color)

            chip = tk.Label(
                list_frame, text=name, bg=color, fg=text_color,
                padx=8, pady=4
            )
            chip.grid(row=row_index, column=0, sticky="w", padx=5, pady=3)

            count_label = tk.Label(
                list_frame, text=f"used by {usage_count} people",
                fg="blue", cursor="hand2"
            )
            count_label.grid(row=row_index, column=1, sticky="w", padx=5)
            count_label.bind(
                "<Button-1>",
                lambda event, tid=tag_id, n=name: open_view_tagged_people(tid, n, refresh_tag_list)
            )

            delete_btn = tk.Button(
                list_frame, text="Delete Tag",
                command=lambda tid=tag_id, n=name, c=usage_count: confirm_delete_tag(tid, n, c)
            )
            delete_btn.grid(row=row_index, column=2, padx=5)

            add_people_btn = tk.Button(
                list_frame, text="Add People",
                command=lambda tid=tag_id, n=name: open_link_people_to_tag(tid, n, refresh_tag_list)
            )
            add_people_btn.grid(row=row_index, column=3, padx=5)

    def confirm_delete_tag(tag_id, name, usage_count):
        confirmed = messagebox.askyesno(
            "Delete Tag",
            f"Delete {name} completely? It is currently used by {usage_count} people "
            f"and will be removed from all of them. This cannot be undone."
        )
        if confirmed:
            delete_tag_completely(connection, tag_id)
            refresh_tag_list()

    refresh_tag_list()

    grip = ResizeGrip(manage_window, manage_window)
    grip.place(relx=1.0, rely=1.0, anchor="se")

def open_view_tagged_people(tag_id, tag_name, on_change=None):
    global tag_subwindow
    close_tag_subwindow()

    view_window = tk.Toplevel(window)
    view_window.attributes("-topmost", True)
    open_near_main(view_window)
    view_window.title(f"People tagged {tag_name}")
    tag_subwindow = view_window
    view_window.protocol("WM_DELETE_WINDOW", lambda: (globals().__setitem__("tag_subwindow", None), view_window.destroy()))

    view_window.grid_columnconfigure(0, weight=1)
    view_window.grid_rowconfigure(0, weight=1)

    row_height = 30
    max_visible_rows = 6

    results_outer = tk.Frame(view_window)
    results_outer.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    results_canvas = tk.Canvas(results_outer, height=row_height * max_visible_rows, highlightthickness=0)
    results_scrollbar = tk.Scrollbar(results_outer, orient="vertical", command=results_canvas.yview)
    results_canvas.configure(yscrollcommand=results_scrollbar.set)

    results_canvas.pack(side="left", fill="both", expand=True)
    results_scrollbar.pack(side="right", fill="y")

    results_frame = tk.Frame(results_canvas)
    results_window_id = results_canvas.create_window((0, 0), window=results_frame, anchor="nw")

    def on_results_canvas_resize(event):
        results_canvas.itemconfig(results_window_id, width=event.width)

    results_canvas.bind("<Configure>", on_results_canvas_resize)

    def on_results_configure(event):
        results_canvas.configure(scrollregion=results_canvas.bbox("all"))

    results_frame.bind("<Configure>", on_results_configure)

    def on_results_mousewheel(event):
        results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    results_canvas.bind("<Enter>", lambda event: results_canvas.bind_all("<MouseWheel>", on_results_mousewheel))
    results_canvas.bind("<Leave>", lambda event: results_canvas.unbind_all("<MouseWheel>"))

    def refresh_list():
        for widget in results_frame.winfo_children():
            widget.destroy()

        cursor.execute("""
            SELECT people.id, people.first_name, people.last_name
            FROM people
            JOIN person_tags ON people.id = person_tags.person_id
            WHERE person_tags.tag_id = ?
            ORDER BY people.first_name
        """, (tag_id,))
        tagged_people = cursor.fetchall()

        if not tagged_people:
            tk.Label(results_frame, text="(no one has this tag)", fg="gray").pack(anchor="w", pady=10)

        for person_id, first_name, last_name in tagged_people:
            row_frame = tk.Frame(results_frame)
            row_frame.pack(fill="x", pady=1)

            name_label = tk.Label(row_frame, text=f"{first_name} {last_name}", anchor="w", cursor="hand2")
            name_label.pack(side="left", fill="x", expand=True, padx=(4, 10))
            name_label.bind("<Button-1>", lambda event, pid=person_id: focus_on_person(pid))

            tk.Button(
                row_frame, text="x", width=2,
                command=lambda pid=person_id: remove_person(pid)
            ).pack(side="right", padx=4)

    def remove_person(person_id):
        remove_tag_from_person(connection, person_id, tag_id)
        refresh_list()
        if on_change:
            on_change()

    refresh_list()

    grip = ResizeGrip(view_window, view_window)
    grip.place(relx=1.0, rely=1.0, anchor="se")

def open_link_people_to_tag(tag_id, tag_name, on_change=None):
    global tag_subwindow
    close_tag_subwindow()

    link_window = tk.Toplevel(window)
    link_window.attributes("-topmost", True)
    open_near_main(link_window)
    link_window.title(f"Add People to {tag_name}")
    tag_subwindow = link_window
    link_window.protocol("WM_DELETE_WINDOW", lambda: (globals().__setitem__("tag_subwindow", None), link_window.destroy()))

    link_window.grid_columnconfigure(0, weight=1)
    link_window.grid_rowconfigure(1, weight=1)

    search_entry = tk.Entry(link_window)
    search_entry.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

    row_height = 30
    max_visible_rows = 6

    results_outer = tk.Frame(link_window)
    results_outer.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    results_canvas = tk.Canvas(results_outer, height=row_height * max_visible_rows, highlightthickness=0)
    results_scrollbar = tk.Scrollbar(results_outer, orient="vertical", command=results_canvas.yview)
    results_canvas.configure(yscrollcommand=results_scrollbar.set)

    results_canvas.pack(side="left", fill="both", expand=True)
    results_scrollbar.pack(side="right", fill="y")

    results_frame = tk.Frame(results_canvas)
    results_window_id = results_canvas.create_window((0, 0), window=results_frame, anchor="nw")

    def on_results_canvas_resize(event):
        results_canvas.itemconfig(results_window_id, width=event.width)

    results_canvas.bind("<Configure>", on_results_canvas_resize)

    def on_results_configure(event):
        results_canvas.configure(scrollregion=results_canvas.bbox("all"))

    results_frame.bind("<Configure>", on_results_configure)

    def on_results_mousewheel(event):
        results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    results_canvas.bind("<Enter>", lambda event: results_canvas.bind_all("<MouseWheel>", on_results_mousewheel))
    results_canvas.bind("<Leave>", lambda event: results_canvas.unbind_all("<MouseWheel>"))

    def refresh_results(filter_text=""):
        for widget in results_frame.winfo_children():
            widget.destroy()
        
        already_tagged_ids = {row[0] for row in cursor.execute(
            "SELECT person_id FROM person_tags WHERE tag_id = ?", (tag_id,)
        ).fetchall()}

        cursor.execute("SELECT id, first_name, last_name FROM people ORDER BY first_name")
        people = cursor.fetchall()

        filter_text = filter_text.strip().lower()

        for row_index, (person_id, first_name, last_name) in enumerate(people):
            if person_id in already_tagged_ids:
                continue

            full_name = f"{first_name} {last_name}"
            if filter_text and filter_text not in full_name.lower():
                continue

            row_frame = tk.Frame(results_frame)
            row_frame.pack(fill="x", pady=1)

            tk.Label(row_frame, text=full_name, anchor="w").pack(side="left", fill="x", expand=True, padx=(4, 10))
            tk.Button(
                row_frame, text="Add",
                command=lambda pid=person_id: add_person_to_tag(pid)
            ).pack(side="right", padx=4)

    def add_person_to_tag(person_id):
        add_tag_to_person(connection, person_id, tag_id)
        refresh_results(search_entry.get())
        if on_change:
            on_change()

    search_entry.bind("<KeyRelease>", lambda event: refresh_results(search_entry.get()))

    refresh_results()

    grip = ResizeGrip(link_window, link_window)
    grip.place(relx=1.0, rely=1.0, anchor="se")

def auto_link_spouses_if_needed(child_id, new_parent_id):
    cursor.execute("SELECT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'parent'", (child_id,))
    other_parent_ids = [row[0] for row in cursor.fetchall() if row[0] != new_parent_id]

    for other_parent_id in other_parent_ids:
        cursor.execute("""
            SELECT 1 FROM relationships
            WHERE relationship_type = 'spouse'
            AND ((person_id = ? AND related_person_id = ?) OR (person_id = ? AND related_person_id = ?))
        """, (new_parent_id, other_parent_id, other_parent_id, new_parent_id))
        already_spouses = cursor.fetchone()

        if not already_spouses:
            cursor.execute("""
                INSERT INTO relationships (person_id, related_person_id, relationship_type)
                VALUES (?, ?, ?)
            """, (new_parent_id, other_parent_id, "spouse"))
            connection.commit()

def pop_out_info():
    if current_info_person_id is None:
        return

    person_id = current_info_person_id

    cursor.execute("SELECT first_name, last_name, birth_date, death_date, sex, notes FROM people WHERE id = ?", (person_id,))
    result = cursor.fetchone()
    if not result:
        return
    first_name, last_name, birth_date, death_date, sex, notes = result

    clear_info_panel()

    popout = tk.Toplevel(window)
    popout.attributes("-topmost", True)
    popout.title(f"{first_name} {last_name}")
    popout.configure(bg="#eeeeee")
    popout.minsize(300, 320)

    button_x = popout_button.winfo_rootx()
    button_y = popout_button.winfo_rooty()
    popout.geometry(f"300x320+{button_x - 310}+{button_y}")

    tk.Label(popout, text=f"{first_name} {last_name}", font=("Arial", 14, "bold"), bg="#eeeeee").pack(anchor="w", padx=12, pady=(12, 6))
    tk.Label(popout, text=f"Born: {birth_date or '—'}", bg="#eeeeee").pack(anchor="w", padx=12)
    tk.Label(popout, text=f"Died: {death_date or '—'}", bg="#eeeeee").pack(anchor="w", padx=12)
    tk.Label(popout, text=f"Sex: {sex or '—'}", bg="#eeeeee").pack(anchor="w", padx=12)

    popout_tags_header = tk.Frame(popout, bg="#eeeeee")
    popout_tags_header.pack(fill="x", padx=12, pady=(12, 0))

    tk.Label(popout_tags_header, text="Tags:", bg="#eeeeee", font=("Arial", 10, "bold")).pack(side="left")
    tk.Button(popout_tags_header, text="Add Tags", command=lambda: open_add_tags_to_person(person_id, refresh_popout_tags)).pack(side="right")

    popout_tags_container = tk.Frame(popout, bg="#eeeeee")
    popout_tags_container.pack(fill="x", padx=12, pady=(4, 12))

    def refresh_popout_tags():
        for widget in popout_tags_container.winfo_children():
            widget.destroy()
        flow = TagFlowView(popout_tags_container, connection, person_id, max_rows=4, on_change=refresh_popout_tags)
        flow.pack(fill="x")

    refresh_popout_tags()

    tk.Label(popout, text="Notes:", font=("Arial", 10, "bold"), bg="#eeeeee").pack(anchor="w", padx=12, pady=(0, 0))
    tk.Label(popout, text=notes or "—", wraplength=350, justify="left", bg="#eeeeee").pack(anchor="w", padx=12, pady=(0, 12))

def on_sidebar_list_configure(event):
    sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))

def get_parent_ids(person_id):
    cursor.execute("SELECT DISTINCT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'parent'", (person_id,))
    return [row[0] for row in cursor.fetchall()]

def get_child_ids(person_id):
       cursor.execute("SELECT DISTINCT person_id FROM relationships WHERE related_person_id = ? AND relationship_type = 'parent'", (person_id,))
       return [row[0] for row in cursor.fetchall()]

def get_spouse_ids(person_id):
       cursor.execute("""
           SELECT DISTINCT related_person_id FROM relationships WHERE person_id = ? AND relationship_type = 'spouse'
           UNION
           SELECT DISTINCT person_id FROM relationships WHERE related_person_id = ? AND relationship_type = 'spouse'
       """, (person_id, person_id))
       return [row[0] for row in cursor.fetchall()]

def get_person_name(person_id):
    cursor.execute("SELECT first_name, last_name FROM people WHERE id = ?", (person_id,))
    row = cursor.fetchone()
    return f"{row[0]} {row[1]}" if row else "(unknown)"

def link_parent(child_id, parent_id):
    if len(get_parent_ids(child_id)) >= 2:
        messagebox.showinfo("Limit reached", "A person can only have 2 linked parents.")
        return
    cursor.execute("INSERT INTO relationships (person_id, related_person_id, relationship_type) VALUES (?, ?, ?)", (child_id, parent_id, "parent"))
    connection.commit()
    auto_link_spouses_if_needed(child_id, parent_id)

def unlink_parent(child_id, parent_id):
    cursor.execute("DELETE FROM relationships WHERE person_id = ? AND related_person_id = ? AND relationship_type = 'parent'", (child_id, parent_id))
    connection.commit()

def link_child(parent_id, child_id):
    if len(get_parent_ids(child_id)) >= 2:
        messagebox.showinfo("Limit reached", f"{get_person_name(child_id)} already has 2 linked parents.")
        return
    cursor.execute("INSERT INTO relationships (person_id, related_person_id, relationship_type) VALUES (?, ?, ?)", (child_id, parent_id, "parent"))
    connection.commit()
    auto_link_spouses_if_needed(child_id, parent_id)

def unlink_child(parent_id, child_id):
    unlink_parent(child_id, parent_id)

def link_spouse(person_id, spouse_id):
    cursor.execute("INSERT INTO relationships (person_id, related_person_id, relationship_type) VALUES (?, ?, ?)", (person_id, spouse_id, "spouse"))
    connection.commit()

def unlink_spouse(person_id, spouse_id):
    cursor.execute("""
        DELETE FROM relationships
        WHERE ((person_id = ? AND related_person_id = ?) OR (person_id = ? AND related_person_id = ?))
        AND relationship_type = 'spouse'
    """, (person_id, spouse_id, spouse_id, person_id))
    connection.commit()

def get_contrasting_text_color(hex_color):
    """Return '#000000' or '#ffffff' depending on which reads better on hex_color."""
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.5 else "#ffffff"

def get_or_create_tag(conn, name, color=None):
    """Return the tag_id for `name`, creating it with `color` if it doesn't exist yet."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tags WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]

    if color is None:
        color = PRESET_COLORS[0]

    cursor.execute(
        "INSERT INTO tags (name, color) VALUES (?, ?)",
        (name.strip(), color)
    )
    conn.commit()
    return cursor.lastrowid

def search_tags(conn, query):
    """Case-insensitive search over tag names, returns list of (id, name, color)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, color FROM tags WHERE name LIKE ? ORDER BY name",
        (f"%{query}%",)
    )
    return cursor.fetchall()

def get_all_tags(conn):
    """Return every tag with how many people currently use it (for Manage Tags window)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tags.id, tags.name, tags.color, COUNT(person_tags.person_id) AS usage_count
        FROM tags
        LEFT JOIN person_tags ON tags.id = person_tags.tag_id
        GROUP BY tags.id
        ORDER BY tags.name
    """)
    return cursor.fetchall()

def get_tags_for_person(conn, person_id):
    """Return all tags (id, name, color) linked to one person."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tags.id, tags.name, tags.color
        FROM tags
        JOIN person_tags ON tags.id = person_tags.tag_id
        WHERE person_tags.person_id = ?
        ORDER BY tags.name
    """, (person_id,))
    return cursor.fetchall()

def add_tag_to_person(conn, person_id, tag_id):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO person_tags (person_id, tag_id) VALUES (?, ?)",
        (person_id, tag_id)
    )
    conn.commit()

def remove_tag_from_person(conn, person_id, tag_id):
    """Unlink one tag from one person. The tag itself stays in the bank."""
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM person_tags WHERE person_id = ? AND tag_id = ?",
        (person_id, tag_id)
    )
    conn.commit()

def delete_tag_completely(conn, tag_id):
    """Delete a tag from the bank entirely. Removes it from every person via CASCADE."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()

def select_manage_tag_color(color):
    manage_tag_selected_color.set(color)
    for swatch, c in manage_tag_swatch_widgets:
        swatch.config(relief="sunken" if c == color else "raised")

def create_tag_from_panel():
    name = manage_tag_name_entry.get().strip()
    if name.startswith("#"):
        name = name[1:]
    if not name:
        return

    existing = search_tags(connection, name)
    exact_match = next((t for t in existing if t[1].lower() == name.lower()), None)

    if exact_match:
        messagebox.showinfo("Tag exists", f"{name} already exists.")
        return

    get_or_create_tag(connection, name, manage_tag_selected_color.get())
    manage_tag_name_entry.delete(0, tk.END)
    refresh_manage_tags_panel()

def confirm_delete_tag_panel(tag_id, name, usage_count):
    confirmed = messagebox.askyesno(
        "Delete Tag",
        f"Delete {name} completely? It is currently used by {usage_count} people "
        f"and will be removed from all of them. This cannot be undone."
    )
    if confirmed:
        delete_tag_completely(connection, tag_id)
        refresh_manage_tags_panel()

def refresh_manage_tags_panel():
    for widget in manage_tags_list_inner.winfo_children():
        widget.destroy()

    tags = get_all_tags(connection)

    for tag_id, name, color, usage_count in tags:
        text_color = get_contrasting_text_color(color)

        row = tk.Frame(manage_tags_list_inner, bg="#eeeeee")
        row.pack(fill="x", pady=4)

        chip = tk.Label(row, text=name, bg=color, fg=text_color, padx=6, pady=2)
        chip.pack(side="left")

        controls_row = tk.Frame(row, bg="#eeeeee")
        controls_row.pack(side="right")

        count_label = tk.Label(
            controls_row, text=f"({usage_count})", bg="#eeeeee",
            fg="blue", cursor="hand2"
        )
        count_label.pack(side="left", padx=(0, 6))
        count_label.bind(
            "<Button-1>",
            lambda event, tid=tag_id, n=name: open_view_tagged_people(tid, n, refresh_manage_tags_panel)
        )

        tk.Button(
            controls_row, text="+", width=2,
            command=lambda tid=tag_id, n=name: open_link_people_to_tag(tid, n, refresh_manage_tags_panel)
        ).pack(side="left", padx=1)

        tk.Button(
            controls_row, text="x", width=2,
            command=lambda tid=tag_id, n=name, c=usage_count: confirm_delete_tag_panel(tid, n, c)
        ).pack(side="left", padx=1)

def close_tag_subwindow():
    global tag_subwindow
    if tag_subwindow is not None:
        try:
            tag_subwindow.destroy()
        except tk.TclError:
            pass
        tag_subwindow = None

def open_add_tags_to_person(person_id, on_change=None):
    global tag_subwindow
    close_tag_subwindow()

    add_window = tk.Toplevel(window)
    add_window.attributes("-topmost", True)
    open_near_main(add_window)
    add_window.title("Add Tags")
    tag_subwindow = add_window
    add_window.protocol("WM_DELETE_WINDOW", lambda: (globals().__setitem__("tag_subwindow", None), add_window.destroy()))

    add_window.grid_columnconfigure(0, weight=1)
    add_window.grid_rowconfigure(1, weight=1)

    search_entry = tk.Entry(add_window)
    search_entry.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

    row_height = 30
    max_visible_rows = 6

    results_outer = tk.Frame(add_window)
    results_outer.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    results_canvas = tk.Canvas(results_outer, height=row_height * max_visible_rows, highlightthickness=0)
    results_scrollbar = tk.Scrollbar(results_outer, orient="vertical", command=results_canvas.yview)
    results_canvas.configure(yscrollcommand=results_scrollbar.set)

    results_canvas.pack(side="left", fill="both", expand=True)
    results_scrollbar.pack(side="right", fill="y")

    results_frame = tk.Frame(results_canvas)
    results_window_id = results_canvas.create_window((0, 0), window=results_frame, anchor="nw")

    def on_results_canvas_resize(event):
        results_canvas.itemconfig(results_window_id, width=event.width)

    results_canvas.bind("<Configure>", on_results_canvas_resize)

    def on_results_configure(event):
        results_canvas.configure(scrollregion=results_canvas.bbox("all"))

    results_frame.bind("<Configure>", on_results_configure)

    def on_results_mousewheel(event):
        results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    results_canvas.bind("<Enter>", lambda event: results_canvas.bind_all("<MouseWheel>", on_results_mousewheel))
    results_canvas.bind("<Leave>", lambda event: results_canvas.unbind_all("<MouseWheel>"))

    def refresh_results(filter_text=""):
        for widget in results_frame.winfo_children():
            widget.destroy()

        already_tagged_ids = {tag_id for tag_id, name, color in get_tags_for_person(connection, person_id)}

        cursor.execute("SELECT id, name, color FROM tags ORDER BY name")
        all_tags = cursor.fetchall()

        filter_text = filter_text.strip().lower()

        for tag_id, name, color in all_tags:
            if tag_id in already_tagged_ids:
                continue
            if filter_text and filter_text not in name.lower():
                continue

            text_color = get_contrasting_text_color(color)

            row_frame = tk.Frame(results_frame)
            row_frame.pack(fill="x", pady=1)

            tk.Label(row_frame, text=name, bg=color, fg=text_color, padx=6, pady=2).pack(side="left", padx=(4, 10))
            tk.Button(
                row_frame, text="Add",
                command=lambda tid=tag_id: add_tag(tid)
            ).pack(side="right", padx=4)

    def add_tag(tag_id):
        add_tag_to_person(connection, person_id, tag_id)
        refresh_results(search_entry.get())
        if on_change:
            on_change()

    search_entry.bind("<KeyRelease>", lambda event: refresh_results(search_entry.get()))
    refresh_results()

    grip = ResizeGrip(add_window, add_window)
    grip.place(relx=1.0, rely=1.0, anchor="se")

       
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

info_tags_header = tk.Frame(info_frame, bg="#eeeeee")
info_tags_header.pack(fill="x", padx=12, pady=(12, 0))

tk.Label(info_tags_header, text="Tags:", bg="#eeeeee", font=("Arial", 10, "bold")).pack(side="left")
tk.Button(info_tags_header, text="Add Tags", command=lambda: open_add_tags_to_person(current_info_person_id, refresh_info_tags)).pack(side="right")

info_tags_container = tk.Frame(info_frame, bg="#eeeeee")
info_tags_container.pack(fill="x", padx=12, pady=(4, 12))

def refresh_info_tags():
    for widget in info_tags_container.winfo_children():
        widget.destroy()
    if current_info_person_id is None:
        return
    flow = TagFlowView(info_tags_container, connection, current_info_person_id, max_rows=4, on_change=refresh_info_tags)
    flow.pack(fill="x")

info_notes_header = tk.Frame(info_frame, bg="#eeeeee")
info_notes_header.pack(fill="x", padx=12, pady=(0, 0))

tk.Label(info_notes_header, text="Notes:", bg="#eeeeee", font=("Arial", 10, "bold")).pack(side="left")
tk.Button(info_notes_header, text="Save Changes", command=lambda: save_notes_changes()).pack(side="right")

info_notes_outer = tk.Frame(info_frame, height=280)
info_notes_outer.pack(fill="x", padx=12, pady=(4, 12))
info_notes_outer.pack_propagate(False)

info_notes_text = tk.Text(info_notes_outer, wrap="word")
info_notes_scrollbar = tk.Scrollbar(info_notes_outer, orient="vertical", command=info_notes_text.yview)
info_notes_text.configure(yscrollcommand=info_notes_scrollbar.set)

info_notes_scrollbar.pack(side="right", fill="y")
info_notes_text.pack(side="left", fill="both", expand=True)

def save_notes_changes():
    if current_info_person_id is None:
        return
    new_notes = info_notes_text.get("1.0", "end-1c")
    cursor.execute("UPDATE people SET notes = ? WHERE id = ?", (new_notes, current_info_person_id))
    connection.commit()

manage_tags_frame = tk.Frame(window, bg="#eeeeee", bd=2, relief="solid")

manage_tags_header = tk.Frame(manage_tags_frame, bg="#dddddd")
manage_tags_header.pack(fill="x")
tk.Label(manage_tags_header, text="Manage Tags", bg="#dddddd", font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=4)
toggle_manage_tags_btn = tk.Button(manage_tags_header, text="▲", width=2, command=toggle_manage_tags)
toggle_manage_tags_btn.pack(side="right", padx=4)

manage_tags_content = tk.Frame(manage_tags_frame, bg="#eeeeee")
manage_tags_content.pack(fill="both", expand=True)

manage_tag_selected_color = tk.StringVar(value=PRESET_COLORS[0])
manage_tag_swatch_widgets = []

manage_tag_swatch_frame = tk.Frame(manage_tags_content, bg="#eeeeee")
manage_tag_swatch_frame.pack(side="bottom", padx=8, pady=(0, 8))

for i, color in enumerate(PRESET_COLORS):
    swatch = tk.Label(manage_tag_swatch_frame, bg=color, width=2, height=1, relief="raised", cursor="hand2")
    swatch.grid(row=0, column=i, padx=1)
    swatch.bind("<Button-1>", lambda e, c=color: select_manage_tag_color(c))
    manage_tag_swatch_widgets.append((swatch, color))

manage_tag_create_row = tk.Frame(manage_tags_content, bg="#eeeeee")
manage_tag_create_row.pack(side="bottom", fill="x", padx=8, pady=(4, 4))

manage_tag_name_entry = tk.Entry(manage_tag_create_row)
manage_tag_name_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))

tk.Button(manage_tag_create_row, text="New Tag", width=10, command=lambda: create_tag_from_panel()).pack(side="right")

manage_tags_canvas = tk.Canvas(manage_tags_content, bg="#eeeeee", highlightthickness=0)
manage_tags_scrollbar = tk.Scrollbar(manage_tags_content, orient="vertical", command=manage_tags_canvas.yview)
manage_tags_canvas.configure(yscrollcommand=manage_tags_scrollbar.set)

manage_tags_scrollbar.pack(side="right", fill="y")
manage_tags_canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))

manage_tags_list_inner = tk.Frame(manage_tags_canvas, bg="#eeeeee")
manage_tags_canvas.create_window((0, 0), window=manage_tags_list_inner, anchor="nw")

manage_tags_list_inner.bind("<Configure>", lambda event: manage_tags_canvas.configure(scrollregion=manage_tags_canvas.bbox("all")))

def on_manage_tags_mousewheel(event):
    manage_tags_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

manage_tags_canvas.bind("<Enter>", lambda event: manage_tags_canvas.bind_all("<MouseWheel>", on_manage_tags_mousewheel))
manage_tags_canvas.bind("<Leave>", lambda event: manage_tags_canvas.unbind_all("<MouseWheel>"))

select_manage_tag_color(PRESET_COLORS[0])
refresh_manage_tags_panel()


window.update()
open_tree_view()
resize_search_list_frame()
refresh_sidebar_list()

window.mainloop()