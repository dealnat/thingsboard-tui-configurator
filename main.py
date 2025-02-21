import curses
import yaml
import os
from typing import Dict, Any, List, Tuple, Optional


class YAMLNode:
    def __init__(self, key: str, value: Any, parent: Optional['YAMLNode'] = None):
        self.key = key
        self.value = value
        self.parent = parent
        self.children: List[YAMLNode] = []
        self.is_leaf = not isinstance(value, dict)
        self.env_var = None
        self.comment = None

        if isinstance(value, str):
            # Extract environment variable and default value if present
            if value.startswith("${") and "}" in value:
                env_part = value[2:value.index("}")]
                if ":" in env_part:
                    self.env_var, default = env_part.split(":", 1)
                else:
                    self.env_var, default = env_part, ""
                self.value = default

        if isinstance(value, dict):
            for k, v in value.items():
                child = YAMLNode(k, v, self)
                self.children.append(child)


class YAMLEditor:
    def __init__(self, stdscr, yaml_file: str):
        self.stdscr = stdscr
        self.yaml_file = yaml_file
        self.root = self.parse_yaml()
        self.current_node = self.root
        self.nav_position = 0
        self.edit_position = 0
        self.edit_mode = False
        self.changes: Dict[str, str] = {}
        self.setup_screen()

    def setup_screen(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)  # Selected item
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Edit mode
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Comments
        curses.init_pair(4, curses.COLOR_GREEN, -1)  # Environment variables

        curses.curs_set(0)
        self.stdscr.keypad(True)

    def parse_yaml(self) -> YAMLNode:
        try:
            with open(self.yaml_file, 'r') as f:
                content = f.read()
                # Split content into lines to preserve comments
                lines = content.split('\n')
                comments = {}

                # Extract comments
                for i, line in enumerate(lines):
                    if '#' in line:
                        key_part = line[:line.index('#')].strip()
                        comment = line[line.index('#'):].strip()
                        if key_part:
                            comments[key_part] = comment

                # Parse YAML
                data = yaml.safe_load(content)
                root = YAMLNode('root', data)

                # Add comments to nodes
                self._add_comments(root, comments)

                return root
        except Exception as e:
            return YAMLNode('root', {'error': f'Failed to load YAML: {str(e)}'})

    def _add_comments(self, node: YAMLNode, comments: Dict[str, str]):
        if node.key in comments:
            node.comment = comments[node.key]
        for child in node.children:
            self._add_comments(child, comments)

    def get_navigable_nodes(self) -> List[YAMLNode]:
        return [node for node in self.current_node.children if not node.is_leaf]

    def get_editable_nodes(self) -> List[YAMLNode]:
        return [node for node in self.current_node.children if node.is_leaf]

    def get_node_path(self, node: YAMLNode) -> str:
        path = []
        current = node
        while current.parent is not None:
            path.append(current.key)
            current = current.parent
        return '_'.join(reversed(path))

    def draw_screen(self):
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        nav_width = width // 3

        # Draw divider
        for y in range(height):
            self.stdscr.addch(y, nav_width, '│')

        # Draw titles
        self.stdscr.addstr(0, 2, "Navigation", curses.A_BOLD)
        self.stdscr.addstr(0, nav_width + 2, "Properties", curses.A_BOLD)

        # Draw navigation items
        nav_items = self.get_navigable_nodes()
        for idx, node in enumerate(nav_items):
            if idx >= height - 3:
                break

            # Prepare the display string
            display = f"  {node.key}"
            if node.comment:
                display = f"{display} {node.comment}"

            if idx == self.nav_position and not self.edit_mode:
                self.stdscr.attron(curses.A_REVERSE)
                self.stdscr.addstr(idx + 2, 2, display)
                self.stdscr.attroff(curses.A_REVERSE)
            else:
                self.stdscr.addstr(idx + 2, 2, display)

        # Draw editable items
        edit_items = self.get_editable_nodes()
        for idx, node in enumerate(edit_items):
            if idx >= height - 3:
                break

            # Prepare the display string
            if node.env_var:
                value_display = f"{node.value} (${node.env_var})"
            else:
                value_display = str(node.value)

            display = f"{node.key}: {value_display}"

            if idx == self.edit_position and self.edit_mode:
                self.stdscr.attron(curses.color_pair(2))
                self.stdscr.addstr(idx + 2, nav_width + 2, display)
                self.stdscr.attroff(curses.color_pair(2))
            else:
                self.stdscr.addstr(idx + 2, nav_width + 2, display)

            # Draw comment if exists
            if node.comment:
                comment_pos = nav_width + 4 + len(display)
                if comment_pos + len(node.comment) < width:
                    self.stdscr.attron(curses.color_pair(3))
                    self.stdscr.addstr(idx + 2, comment_pos, node.comment)
                    self.stdscr.attroff(curses.color_pair(3))

        # Draw current path
        path = self.get_node_path(self.current_node)
        path_display = f"Path: {path}" if path else "Path: /"
        self.stdscr.addstr(height - 2, 2, path_display, curses.A_DIM)

        # Draw help text
        help_text = "TAB: Toggle Edit | ENTER: Select/Edit | ESC: Back/Exit | ↑↓: Navigate"
        self.stdscr.addstr(height - 1, 2, help_text, curses.A_DIM)

        self.stdscr.refresh()

    def edit_value(self, node: YAMLNode):
        height, width = self.stdscr.getmaxyx()

        # Create edit window
        edit_win = curses.newwin(5, width - 4, height - 6, 2)
        edit_win.box()
        key_name = f"Edit {node.key}"
        env_name = f"ENV: ${node.env_var}"
        edit_win.addstr(0, 2, key_name)

        if node.env_var:
            edit_win.addstr(0, width - len(env_name) - 5, env_name )

        current_value = str(node.value)
        edit_win.addstr(1, 2, f"Current: {current_value}")
        edit_win.addstr(2, 2, "New value: ")
        edit_win.refresh()

        # Enable cursor and echo for input
        curses.echo()
        curses.curs_set(2)

        # Get input
        edit_win.move(2,  13)
        new_value = edit_win.getstr().decode('utf-8')

        # Restore cursor and echo settings
        curses.noecho()
        curses.curs_set(0)

        if new_value:
            node.value = new_value
            # Save to export.env
            env_name = node.env_var if node.env_var else self.get_node_path(node)
            self.changes[env_name] = new_value
            self.save_changes()

    def save_changes(self):
        with open('export.env', 'w') as f:
            for env_name, value in self.changes.items():
                f.write(f"export {env_name}={value}\n")

    def handle_navigation(self, key):
        if key == curses.KEY_UP:
            if self.edit_mode:
                self.edit_position = max(0, self.edit_position - 1)
            else:
                self.nav_position = max(0, self.nav_position - 1)
        elif key == curses.KEY_DOWN:
            if self.edit_mode:
                edit_items = self.get_editable_nodes()
                if edit_items:
                    self.edit_position = min(len(edit_items) - 1, self.edit_position + 1)
            else:
                nav_items = self.get_navigable_nodes()
                if nav_items:
                    self.nav_position = min(len(nav_items) - 1, self.nav_position + 1)
        elif key == ord('\t'):
            self.edit_mode = not self.edit_mode
            self.nav_position = 0  # Reset position when switching tabs
            self.edit_position = 0
        elif key == ord('\n'):
            if self.edit_mode:
                edit_items = self.get_editable_nodes()
                if edit_items and 0 <= self.edit_position < len(edit_items):
                    self.edit_value(edit_items[self.edit_position])
            else:
                nav_items = self.get_navigable_nodes()
                if nav_items and 0 <= self.nav_position < len(nav_items):
                    self.current_node = nav_items[self.nav_position]
                    self.nav_position = 0  # Reset to top when entering a node
                    self.edit_position = 0
        elif key == 27:  # ESC
            if self.edit_mode:
                self.edit_mode = False
            elif self.current_node.parent:
                self.current_node = self.current_node.parent
                self.nav_position = 0
                self.edit_position = 0
            else:
                return False  # Exit program if at root
        return True

    def run(self):
        running = True
        while running:
            self.draw_screen()
            key = self.stdscr.getch()
            running = self.handle_navigation(key)


def main(stdscr, yaml_file: str):
    editor = YAMLEditor(stdscr, yaml_file)
    editor.run()


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python yaml_editor.py <yaml_file>")
        sys.exit(1)

    curses.wrapper(main, sys.argv[1])