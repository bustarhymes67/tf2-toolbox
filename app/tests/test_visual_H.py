"""Visual pass task H: the shared design system in web/index.html (fonts, colours, spacing,
motion), the window shell's wording, and the Chat / Status / Help pages' new layout. Reads the
files only (no window)."""
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(APP, path), encoding="utf-8") as f:
        return f.read()


def root_vars(css):
    block = re.search(r":root\{(.*?)\n\}", css, re.S).group(1)
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block))


class VisualHTest(unittest.TestCase):
    def setUp(self):
        self.index = read("web/index.html")
        self.bridge = read("web/bridge.js")
        self.page = read("web/pages/chat_status_help.js")
        self.css = read("web/pages/chat_status_help.css")
        self.vars = root_vars(self.index)

    def test_shared_variables(self):
        v = self.vars
        self.assertIn("Bahnschrift", v["--f-head"])
        self.assertTrue(v["--f-num"].startswith('"Cascadia Code"'))
        self.assertIn("Consolas", v["--f-num"])
        self.assertIn("--f-text", v)
        self.assertEqual((v["--g1"], v["--g2"], v["--g3"]), ("8px", "16px", "24px"))
        for name in ("--bad", "--warn", "--ac"):
            self.assertIn(name, v)
        # The older names keep working.
        for name in ("--f-ui", "--f-lab", "--s1", "--s2", "--s3", "--red", "--org", "--sp2"):
            self.assertIn(name, v)
        self.assertEqual(v["--f-lab"], "var(--f-head)")
        self.assertEqual(v["--f-ui"], "var(--f-text)")

    def test_motion(self):
        self.assertEqual(self.vars["--fade"], ".1s")
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.index)
        self.assertRegex(self.index, r"\.nav,[^{]*\.btn,[^{]*\.pill[^{]*\{transition:[^}]*var\(--fade\)")
        self.assertIn("transition:opacity var(--fade)", self.css)  # the command pills' hover fades in

    def test_shell(self):
        self.assertIn("grid-template-rows:32px 1fr", self.index)  # title bar 4 px shorter
        self.assertNotRegex(self.index + self.bridge, re.compile("hides this", re.I))
        self.assertIn("show / hide", self.bridge)
        self.assertRegex(self.index, r"\.hint\{[^}]*opacity:\.7")
        self.assertIn('{"History": "Bans", "Lists": "Cheater lists"}', self.bridge)
        self.assertIn('data-light="${esc(l.name)}"', self.bridge)  # the data keeps its key
        # Badges: neutral unless they count cheaters; no made-up numbers in the markup.
        self.assertRegex(self.index, r"\.nav \.badge\{[^}]*background:transparent")
        self.assertIn('const RED_BADGES = new Set(["Players", "Cheat check"])', self.bridge)
        self.assertNotIn('class="badge', self.index)
        # Thin outline icons: one stroke width.
        widths = set(re.findall(r"\.(?:nav|btn|wbtn) svg\{[^}]*stroke-width:([\d.]+)", self.index))
        self.assertEqual(widths, {"1.5"})

    def test_brackets_and_switch(self):
        # Brackets only where a page opts in with "brk"; the plain panel has none.
        self.assertNotRegex(self.index, r"\.pnl::(before|after)")
        self.assertIn(".brk::before", self.index)
        self.assertEqual(self.page.count('"pnl brk'), 3)  # Chat, Status, Help: one main panel each
        self.assertEqual(self.page.count("brk"), 3)
        self.assertRegex(self.index, r"\.sw\{[^}]*background:#232b35")  # OFF: grey track

    def test_status_and_help_layout(self):
        self.assertIn('class="srow"', self.page)
        self.assertRegex(self.css, r"#p-status \.srow\{display:grid;grid-template-columns:[^;]+;")
        self.assertIn("hman", self.page)
        self.assertNotIn("hgrid", self.page)  # one column, not the old 3-column grid
        self.assertIn("Open the ${esc(c.link.page)} page", self.page)  # verb + what

    def test_numbers_font_only_for_numbers(self):
        # The Chat page's texts (posts, previews, pills, hints) use the text font.
        for sel in ("#p-chat .chatlog{font-family:var(--f-text)", "#p-chat .pill{position:relative;font-family:var(--f-text)",
                    "#p-chat .cpreview .pl{font-family:var(--f-text)", "#p-chat .phint{margin-left:auto;font-family:var(--f-text)"):
            self.assertIn(sel, self.css)
        self.assertNotIn("Mute !speak", self.page)


if __name__ == "__main__":
    unittest.main()
