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
        self.changes: Dict[str, str] = {}
        self.original_values: Dict[str, str] = {}  # Store original values
        self.load_env_file()
        self.root = self.parse_yaml()
        self.current_node = self.root
        self.nav_position = 0
        self.scroll_offset = 0  # Add scroll offset
        self.edit_position = 0
        self.edit_scroll_offset = 0  # Add scroll offset for edit pane
        self.edit_mode = False
        self.setup_screen()

    def setup_screen(self):
        curses.set_escdelay(1)  # Fix ESC delay
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)

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

                # Update values from loaded environment variables
                self._update_node_values(root)

                return root
        except Exception as e:
            return YAMLNode('root', {'error': f'Failed to load YAML: {str(e)}'})

    def _update_node_values(self, node: YAMLNode):
        """Update node values with values from export.env"""
        if node.env_var and node.env_var in self.changes:
            node.value = self.changes[node.env_var]
        elif not node.env_var and node.is_leaf:
            # Check if there's a value for the full path
            node_path = self.get_node_path(node)
            if node_path in self.changes:
                node.value = self.changes[node_path]

        for child in node.children:
            self._update_node_values(child)

    def _add_comments(self, node: YAMLNode, comments: Dict[str, str]):
        if node.key in comments:
            node.comment = comments[node.key]
        for child in node.children:
            self._add_comments(child, comments)

    def get_node_path(self, node: YAMLNode) -> str:
        path = []
        current = node
        while current.parent is not None:
            path.append(current.key)
            current = current.parent
        return '_'.join(reversed(path))
    def load_env_file(self):
        try:
            if os.path.exists('export.env'):
                with open('export.env', 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('export '):
                            env_setting = line[7:]
                            if '=' in env_setting:
                                name, value = env_setting.split('=', 1)
                                value = value.strip('"\'')
                                self.changes[name] = value
                                self.original_values[name] = value  # Store original value
        except Exception as e:
            self.stdscr.addstr(0, 0, f"Error loading env file: {str(e)}")
            self.stdscr.refresh()
            curses.napms(2000)

    def has_unsaved_changes(self) -> bool:
        return self.changes != self.original_values

    def confirm_exit(self) -> bool:
        if not self.has_unsaved_changes():
            return True

        height, width = self.stdscr.getmaxyx()
        confirm_win = curses.newwin(5, 40, height // 2 - 2, width // 2 - 20)
        confirm_win.box()
        confirm_win.addstr(1, 2, "Unsaved changes. Save before exit?")
        confirm_win.addstr(3, 2, "[Y]es  [N]o  [C]ancel")
        confirm_win.refresh()

        while True:
            key = self.stdscr.getch()
            if key in [ord('y'), ord('Y')]:
                self.save_changes()
                return False
            elif key in [ord('n'), ord('N')]:
                return False
            elif key in [ord('c'), ord('C'), 27]:  # 'C' or ESC
                return True

    def save_changes(self):
        with open('export.env', 'w') as f:
            for env_name, value in self.changes.items():
                f.write(f"export {env_name}={value}\n")
    def get_navigable_nodes(self) -> List[YAMLNode]:
        return [node for node in self.current_node.children if not node.is_leaf]

    def get_editable_nodes(self) -> List[YAMLNode]:
        return [node for node in self.current_node.children if node.is_leaf]

    def draw_screen(self):
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        nav_width = width // 3
        max_display_items = height - 4  # Reserve space for header and footer

        # Draw divider
        for y in range(height):
            self.stdscr.addch(y, nav_width, '│')

        # Draw titles
        self.stdscr.addstr(0, 2, "Navigation", curses.A_BOLD)
        self.stdscr.addstr(0, nav_width + 2, "Properties", curses.A_BOLD)

        # Draw navigation items with scrolling
        nav_items = self.get_navigable_nodes()
        visible_nav_items = nav_items[self.scroll_offset:self.scroll_offset + max_display_items]

        for idx, node in enumerate(visible_nav_items):
            if idx >= max_display_items:
                break

            display = f"  {node.key}"
            if node.comment:
                display = f"{display} {node.comment}"

            actual_idx = idx + self.scroll_offset
            if actual_idx == self.nav_position and not self.edit_mode:
                self.stdscr.attron(curses.A_REVERSE)
                self.stdscr.addstr(idx + 2, 2, display[:nav_width - 3])
                self.stdscr.attroff(curses.A_REVERSE)
            else:
                self.stdscr.addstr(idx + 2, 2, display[:nav_width - 3])

        # Draw editable items with scrolling
        edit_items = self.get_editable_nodes()
        visible_edit_items = edit_items[self.edit_scroll_offset:self.edit_scroll_offset + max_display_items]

        for idx, node in enumerate(visible_edit_items):
            if idx >= max_display_items:
                break

            if node.env_var:
                value_display = f"{node.value} (${node.env_var})"
            else:
                value_display = str(node.value)

            display = f"{node.key}: {value_display}"
            actual_idx = idx + self.edit_scroll_offset

            if actual_idx == self.edit_position and self.edit_mode:
                self.stdscr.attron(curses.color_pair(2))
                self.stdscr.addstr(idx + 2, nav_width + 2, display)
                self.stdscr.attroff(curses.color_pair(2))
            else:
                self.stdscr.addstr(idx + 2, nav_width + 2, display)

            if node.comment:
                comment_pos = nav_width + 4 + len(display)
                if comment_pos + len(node.comment) < width:
                    self.stdscr.attron(curses.color_pair(3))
                    self.stdscr.addstr(idx + 2, comment_pos, node.comment)
                    self.stdscr.attroff(curses.color_pair(3))

        # Draw scroll indicators
        if len(nav_items) > max_display_items:
            if self.scroll_offset > 0:
                self.stdscr.addstr(1, nav_width - 2, "↑")
            if self.scroll_offset + max_display_items < len(nav_items):
                self.stdscr.addstr(height - 2, nav_width - 2, "↓")

        if len(edit_items) > max_display_items:
            if self.edit_scroll_offset > 0:
                self.stdscr.addstr(1, width - 2, "↑")
            if self.edit_scroll_offset + max_display_items < len(edit_items):
                self.stdscr.addstr(height - 2, width - 2, "↓")

        # Draw current path and help text
        path = self.get_node_path(self.current_node)
        path_display = f"Path: {path}" if path else "Path: /"
        self.stdscr.addstr(height - 2, 2, path_display, curses.A_DIM)

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
            edit_win.addstr(0, width - len(env_name) - 5, env_name)

        current_value = str(node.value)
        edit_win.addstr(1, 2, f"Current: {current_value}")
        edit_win.addstr(2, 2, "New value: ")
        edit_win.refresh()

        # Enable cursor and echo for input
        curses.echo()
        curses.curs_set(2)

        # Get input
        edit_win.move(2, 13)
        new_value = edit_win.getstr().decode('utf-8')

        # Restore cursor and echo settings
        curses.noecho()
        curses.curs_set(0)

        if new_value:
            node.value = new_value
            # Save to export.env
            env_name = node.env_var if node.env_var else self.get_node_path(node)
            self.changes[env_name] = new_value
    def handle_navigation(self, key):
        if key == curses.KEY_UP:
            if self.edit_mode:
                if self.edit_position > 0:
                    self.edit_position -= 1
                    if self.edit_position < self.edit_scroll_offset:
                        self.edit_scroll_offset = self.edit_position
            else:
                if self.nav_position > 0:
                    self.nav_position -= 1
                    if self.nav_position < self.scroll_offset:
                        self.scroll_offset = self.nav_position
        elif key == curses.KEY_DOWN:
            items = self.get_editable_nodes() if self.edit_mode else self.get_navigable_nodes()
            max_pos = len(items) - 1

            if self.edit_mode:
                if self.edit_position < max_pos:
                    self.edit_position += 1
                    height = self.stdscr.getmaxyx()[0] - 4
                    if self.edit_position >= self.edit_scroll_offset + height:
                        self.edit_scroll_offset = self.edit_position - height + 1
            else:
                if self.nav_position < max_pos:
                    self.nav_position += 1
                    height = self.stdscr.getmaxyx()[0] - 4
                    if self.nav_position >= self.scroll_offset + height:
                        self.scroll_offset = self.nav_position - height + 1
        elif key == ord('\t'):
            self.edit_mode = not self.edit_mode
        elif key == ord('\n'):
            if self.edit_mode:
                edit_items = self.get_editable_nodes()
                if edit_items and 0 <= self.edit_position < len(edit_items):
                    self.edit_value(edit_items[self.edit_position])
            else:
                nav_items = self.get_navigable_nodes()
                if nav_items and 0 <= self.nav_position < len(nav_items):
                    self.current_node = nav_items[self.nav_position]
                    self.nav_position = 0
                    self.scroll_offset = 0
                    self.edit_position = 0
                    self.edit_scroll_offset = 0
        elif key == 27:  # ESC
            if self.edit_mode:
                self.edit_mode = False
            elif self.current_node.parent:
                self.current_node = self.current_node.parent
                self.nav_position = 0
                self.scroll_offset = 0
                self.edit_position = 0
                self.edit_scroll_offset = 0
            else:
                return self.confirm_exit()
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