"""Unit and integration tests for Blink Encrypted Bookmarks Vault & Browser Bridge."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bookmarks_browser_bridge import (
    detect_active_browser_windows,
    discover_all_browser_profiles,
)
from bookmarks_vault import (
    BookmarksVault,
    aead_decrypt,
    aead_encrypt,
    extract_domain_label,
    generate_recovery_key,
    normalize_bookmark_url,
    normalize_recovery_key,
    parse_clipboard_spreadsheet,
)


class TestBookmarksVaultAndBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.vault_file = Path(self.tmp_dir.name) / "blink-vault.json"
        self.vault = BookmarksVault(self.vault_file)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_aead_encrypt_decrypt_roundtrip_and_tamper_detection(self) -> None:
        key = b"K" * 32
        secret_msg = "灵动书签 AES-256-GCM 硬件级加密测试".encode("utf-8")
        box = aead_encrypt(key, secret_msg)
        self.assertIn(box["alg"], ("aes-256-gcm", "blake2b-hmac-sha256"))
        recovered = aead_decrypt(key, box)
        self.assertEqual(recovered, secret_msg)

        # Wrong key must fail
        with self.assertRaises(ValueError):
            aead_decrypt(b"W" * 32, box)

    def test_url_normalization_and_security_scheme_filter(self) -> None:
        self.assertEqual(
            normalize_bookmark_url("github.com/dedeyuyu/Blink"),
            "https://github.com/dedeyuyu/Blink",
        )
        self.assertEqual(
            extract_domain_label("https://www.github.com/dedeyuyu/Blink"),
            "github.com",
        )
        for dangerous in ("javascript:alert(1)", "data:text/html,hi", "file:///C:/Windows"):
            with self.assertRaises(ValueError):
                normalize_bookmark_url(dangerous)

    def test_vault_lifecycle_and_lossless_recovery_key_reset(self) -> None:
        self.assertFalse(self.vault.is_initialized())
        self.assertFalse(self.vault.is_unlocked())

        # 1. Initialize vault with master password
        recovery_key = self.vault.initialize_vault("MySecretPass123")
        self.assertTrue(recovery_key.startswith("BK-"))
        self.assertEqual(len(normalize_recovery_key(recovery_key)), 16)
        self.assertTrue(self.vault.is_initialized())
        self.assertTrue(self.vault.is_unlocked())

        # 2. Add a custom category and bookmark before locking
        cat = self.vault.add_category("核心战略项目", "emerald")
        bm = self.vault.add_bookmark(
            title="Blink 灵动书签源码",
            url="https://github.com/dedeyuyu/Blink",
            category_id=cat["id"],
            note="桌面悬浮加密书签参考实现",
            pinned=True,
        )
        total_before = len(self.vault.get_bookmarks())
        self.assertGreaterEqual(total_before, 4)

        # 3. Lock vault and verify memory is cleared
        self.vault.lock()
        self.assertFalse(self.vault.is_unlocked())

        # 4. Wrong password fails
        ok, _msg = self.vault.unlock("WrongPassword999")
        self.assertFalse(ok)
        self.assertFalse(self.vault.is_unlocked())

        # 5. Forgot password -> Reset password using Recovery Key (Strategy 2)
        ok_rec, msg_rec = self.vault.reset_password_with_recovery_key(
            recovery_key, "BrandNewPass888"
        )
        self.assertTrue(ok_rec, msg_rec)
        self.assertTrue(self.vault.is_unlocked())

        # 6. Verify 100% of bookmarks and categories are preserved without data loss!
        bms_after = self.vault.get_bookmarks()
        self.assertEqual(len(bms_after), total_before)
        found = [b for b in bms_after if b["id"] == bm["id"]]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Blink 灵动书签源码")
        self.assertEqual(found[0]["note"], "桌面悬浮加密书签参考实现")
        self.assertTrue(found[0]["pinned"])

        # 7. Lock and unlock with the new password
        self.vault.lock()
        ok_new, _ = self.vault.unlock("BrandNewPass888")
        self.assertTrue(ok_new)

        # 8. Change password & regenerate recovery key
        ok_chg, _ = self.vault.change_password("BrandNewPass888", "UpdatedPass777")
        self.assertTrue(ok_chg)
        ok_regen, new_rec_key = self.vault.regenerate_recovery_key("UpdatedPass777")
        self.assertTrue(ok_regen)
        self.assertNotEqual(new_rec_key, recovery_key)

    def test_additive_html_import_and_dual_track_export(self) -> None:
        rec_key = self.vault.initialize_vault("ExportTest123")
        initial_count = len(self.vault.get_bookmarks())

        sample_html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
        <DL><p>
            <DT><H3>团队研发工具</H3>
            <DL><p>
                <DT><A HREF="https://news.ycombinator.com" DATA-BLINK-NOTE="科技资讯" DATA-BLINK-PINNED="1">Hacker News</A>
                <DT><A HREF="https://huggingface.co">Hugging Face</A>
            </DL><p>
        </DL><p>
        """
        added_bms, added_cats = self.vault.import_html_additive(sample_html)
        self.assertEqual(added_bms, 2)
        self.assertEqual(added_cats, 1)
        self.assertEqual(len(self.vault.get_bookmarks()), initial_count + 2)

        # Re-importing the same HTML is idempotent (skips duplicates)
        dup_bms, dup_cats = self.vault.import_html_additive(sample_html)
        self.assertEqual(dup_bms, 0)
        self.assertEqual(dup_cats, 0)

        # Export HTML and verify contents
        exported_html = self.vault.export_html()
        self.assertIn("Hacker News", exported_html)
        self.assertIn("https://huggingface.co", exported_html)

        # Export encrypted .blinkbak and restore into a second fresh vault
        bak_path = Path(self.tmp_dir.name) / "test_backup.blinkbak"
        self.vault.export_encrypted_backup(bak_path)
        self.assertTrue(bak_path.is_file())

        vault2 = BookmarksVault(Path(self.tmp_dir.name) / "vault2.json")
        vault2.initialize_vault("SecondVaultPass")
        restored_bms, _ = vault2.import_encrypted_backup(bak_path, rec_key)
        self.assertGreaterEqual(restored_bms, 2)

    def test_category_reorder_and_bookmark_move_to_category(self) -> None:
        self.vault.initialize_vault("ReorderPass123")
        cats_before = self.vault.get_categories()
        ids_before = [c["id"] for c in cats_before]
        self.assertGreaterEqual(len(ids_before), 3)

        # Move last category to index 0
        last_id = ids_before[-1]
        self.vault.move_category_to_index(last_id, 0)
        cats_after = self.vault.get_categories()
        self.assertEqual(cats_after[0]["id"], last_id)

        # Reorder categories explicitly
        reversed_ids = list(reversed([c["id"] for c in cats_after]))
        self.vault.reorder_categories(reversed_ids)
        self.assertEqual([c["id"] for c in self.vault.get_categories()], reversed_ids)

        # Move bookmark to another category
        bm = self.vault.add_bookmark("MoveMe", "https://example.org/move", category_id=reversed_ids[0])
        target_cid = reversed_ids[-1]
        updated = self.vault.move_bookmark_to_category(bm["id"], target_cid)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["categoryId"], target_cid)

    def test_browser_bridge_enumeration_safe(self) -> None:
        wins = detect_active_browser_windows()
        self.assertIsInstance(wins, list)
        profs = discover_all_browser_profiles()
        self.assertIsInstance(profs, list)

    def test_bookmark_vertical_reorder_and_pinned_boundary_sync(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            v = BookmarksVault(Path(td) / "reorder.json")
            v.initialize_vault("Pass1234")
            cat_id = v.get_categories()[0]["id"]
            b1 = v.add_bookmark("Site A", "https://a.example.com", category_id=cat_id, pinned=True)
            b2 = v.add_bookmark("Site B", "https://b.example.com", category_id=cat_id, pinned=False)
            b3 = v.add_bookmark("Site C", "https://c.example.com", category_id=cat_id, pinned=False)

            # Reorder unpinned b2 and b3 within cat_id
            items_before = v.get_bookmarks(category_id=cat_id)
            unpinned_before = [b["id"] for b in items_before if not b["pinned"]]
            self.assertIn(b2["id"], unpinned_before)
            self.assertIn(b3["id"], unpinned_before)

            desired_order = [b["id"] for b in items_before if b["pinned"]] + [b2["id"], b3["id"]]
            v.reorder_bookmarks(desired_order, moved_bookmark_id=b2["id"])
            items_after = v.get_bookmarks(category_id=cat_id)
            unpinned_after = [b["id"] for b in items_after if not b["pinned"]]
            self.assertEqual(unpinned_after[:2], [b2["id"], b3["id"]])

            # Now swap b3 above b2
            desired_order2 = [b["id"] for b in items_after if b["pinned"]] + [b3["id"], b2["id"]]
            v.reorder_bookmarks(desired_order2, moved_bookmark_id=b3["id"])
            items_after2 = v.get_bookmarks(category_id=cat_id)
            unpinned_after2 = [b["id"] for b in items_after2 if not b["pinned"]]
            self.assertEqual(unpinned_after2[:2], [b3["id"], b2["id"]])

            # Drag unpinned b3 above pinned b1 -> b3 auto-becomes pinned=True!
            desired_order3 = [b3["id"], b1["id"]] + [
                b["id"] for b in items_after2 if b["id"] not in (b3["id"], b1["id"])
            ]
            v.reorder_bookmarks(desired_order3, moved_bookmark_id=b3["id"])
            items_after3 = v.get_bookmarks(category_id=cat_id)
            self.assertEqual(items_after3[0]["id"], b3["id"])
            self.assertTrue(items_after3[0]["pinned"])

    def test_google_sheets_clipboard_parse_and_batch_import(self) -> None:
        self.vault.initialize_vault("SheetPass123")

        # ── Scenario 1: Single-column 100 hyperlinks copied from Google Sheets into a specific folder ──
        target_cat = self.vault.add_category("独立站精选100", "cyan")
        rows_100 = "".join(
            f'<tr><td data-sheets-hyperlink="https://shop{i}.example.com/item">'
            f'<a href="https://www.google.com/url?q=https://shop{i}.example.com/item&amp;sa=D">独立站商品 #{i}</a>'
            f"</td></tr>"
            for i in range(1, 101)
        )
        sheet_html_100 = f'<google-sheets-html-origin><table><tbody>{rows_100}</tbody></table>'
        parsed_100 = parse_clipboard_spreadsheet(html_text=sheet_html_100, plain_text="")
        self.assertEqual(parsed_100["recommended_mode"], "single_category")
        self.assertEqual(len(parsed_100["flat_items"]), 100)
        self.assertEqual(parsed_100["flat_items"][0]["title"], "独立站商品 #1")
        self.assertEqual(parsed_100["flat_items"][0]["url"], "https://shop1.example.com/item")
        self.assertEqual(parsed_100["flat_items"][99]["title"], "独立站商品 #100")

        added_bms, added_cats, first_cid = self.vault.import_clipboard_batches(
            [{"category_id": target_cat["id"], "items": parsed_100["flat_items"]}],
            skip_duplicates=True,
        )
        self.assertEqual(added_bms, 100)
        self.assertEqual(added_cats, 0)
        self.assertEqual(first_cid, target_cat["id"])
        cat_bms = self.vault.get_bookmarks(category_id=target_cat["id"])
        self.assertEqual(len(cat_bms), 100)
        self.assertEqual(cat_bms[0]["title"], "独立站商品 #1")
        self.assertEqual(cat_bms[99]["title"], "独立站商品 #100")

        # ── Scenario 2: Multi-column A-Z Google Sheets table (Row 1 = Folder names, Row 2+ = Hyperlinks) ──
        # Includes colspan="1" on row 3 where Column B is empty and Column C has a link!
        multi_col_html = """
        <google-sheets-html-origin>
        <table><tbody>
            <tr>
                <td>AI 绘画工具</td>
                <td>跨境电商工具</td>
                <td>社媒运营矩阵</td>
            </tr>
            <tr>
                <td><a href="https://midjourney.com">Midjourney</a></td>
                <td><a href="https://www.shopify.com">Shopify 后台</a></td>
                <td data-sheets-hyperlink="https://x.com/home">X (Twitter)</td>
            </tr>
            <tr>
                <td><a href="https://leonardo.ai">Leonardo AI</a></td>
                <td colspan="1"></td>
                <td><a href="https://www.tiktok.com">TikTok 创作者中心</a></td>
            </tr>
        </tbody></table>
        """
        parsed_multi = parse_clipboard_spreadsheet(html_text=multi_col_html, plain_text="")
        self.assertEqual(parsed_multi["recommended_mode"], "matrix_headers")
        cols = parsed_multi["header_columns"]
        self.assertEqual(len(cols), 3)
        self.assertEqual(cols[0]["category_name"], "AI 绘画工具")
        self.assertEqual([x["title"] for x in cols[0]["items"]], ["Midjourney", "Leonardo AI"])
        self.assertEqual(cols[1]["category_name"], "跨境电商工具")
        self.assertEqual([x["title"] for x in cols[1]["items"]], ["Shopify 后台"])
        self.assertEqual(cols[2]["category_name"], "社媒运营矩阵")
        self.assertEqual([x["title"] for x in cols[2]["items"]], ["X (Twitter)", "TikTok 创作者中心"])

        batches = [
            {"category_name": c["category_name"], "items": c["items"]}
            for c in cols
        ]
        m_bms, m_cats, _ = self.vault.import_clipboard_batches(batches, skip_duplicates=True)
        self.assertEqual(m_bms, 5)
        self.assertEqual(m_cats, 3)

        cats_by_name = {c["name"]: c["id"] for c in self.vault.get_categories()}
        self.assertIn("AI 绘画工具", cats_by_name)
        self.assertIn("跨境电商工具", cats_by_name)
        self.assertIn("社媒运营矩阵", cats_by_name)
        ai_items = self.vault.get_bookmarks(category_id=cats_by_name["AI 绘画工具"])
        self.assertEqual([b["title"] for b in ai_items], ["Midjourney", "Leonardo AI"])
        social_items = self.vault.get_bookmarks(category_id=cats_by_name["社媒运营矩阵"])
        self.assertEqual([b["title"] for b in social_items], ["X (Twitter)", "TikTok 创作者中心"])



class TestBookmarksPyQt6UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from PyQt6.QtWidgets import QApplication
            cls.app = QApplication.instance() or QApplication([])
            cls.has_qt = True
        except Exception:
            cls.has_qt = False

    def test_orb_and_floating_panel_lifecycle_and_scaling(self) -> None:
        if not self.has_qt:
            self.skipTest("PyQt6 not available in current interpreter")
        from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication
        from bookmarks_ui import BookmarkOrbWidget, BookmarksFloatingPanel
        from world_clock_ui import FloatingWorldClock

        with tempfile.TemporaryDirectory() as td:
            vault = BookmarksVault(Path(td) / "ui-vault.json")
            orb = BookmarkOrbWidget()
            orb.set_orb_size(32)
            self.assertEqual(orb.width(), 32)
            orb.set_orb_size(56)
            self.assertEqual(orb.width(), 56)

            panel = BookmarksFloatingPanel(vault=vault)
            # Verify all 8-direction edge/corner resize handles via real QMouseEvent
            self.assertEqual(len(panel._resize_handles), 8)
            for direction in (
                "Right",
                "Bottom",
                "BottomRight",
                "Left",
                "Top",
                "TopLeft",
                "TopRight",
                "BottomLeft",
            ):
                panel.setGeometry(300, 200, 420, 540)
                hw = panel._resize_handles[direction]
                start_g = QPointF(500.0, 500.0)
                press_ev = QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(2.0, 2.0),
                    start_g,
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                hw.mousePressEvent(press_ev)
                dx = -40.0 if "Left" in direction else (40.0 if "Right" in direction else 0.0)
                dy = -40.0 if "Top" in direction else (40.0 if "Bottom" in direction else 0.0)
                move_ev = QMouseEvent(
                    QEvent.Type.MouseMove,
                    QPointF(2.0 + dx, 2.0 + dy),
                    QPointF(500.0 + dx, 500.0 + dy),
                    Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                hw.mouseMoveEvent(move_ev)
                rel_ev = QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(2.0 + dx, 2.0 + dy),
                    QPointF(500.0 + dx, 500.0 + dy),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                hw.mouseReleaseEvent(rel_ev)
                if "Left" in direction or "Right" in direction:
                    self.assertEqual(panel.width(), 460, f"Failed width resize for {direction}")
                if "Top" in direction or "Bottom" in direction:
                    self.assertEqual(panel.height(), 580, f"Failed height resize for {direction}")

            panel.resize(420, 540)
            base_scale = panel._ui_scale
            panel.resize(620, 760)
            panel._apply_proportional_scale()
            self.assertGreater(panel._ui_scale, base_scale)
            panel.resize(420, 540)
            panel._apply_proportional_scale()

            # Initially uninitialized -> page 0 (setup), sub-page 0 (password form)
            self.assertEqual(panel.stack.currentIndex(), 0)
            self.assertEqual(panel.setup_sub_stack.currentIndex(), 0)

            # Simulate user setting password via UI buttons -> transitions to in-panel Recovery Key step (sub-page 1)
            panel.setup_pwd1.setText("UiPass1234")
            panel.setup_pwd2.setText("UiPass1234")
            panel.btn_init_vault.click()
            self.assertTrue(vault.is_initialized())
            self.assertTrue(vault.is_unlocked())
            self.assertEqual(panel.stack.currentIndex(), 0)
            self.assertEqual(panel.setup_sub_stack.currentIndex(), 1)
            rec_key = panel.setup_key_label.text().strip()
            self.assertTrue(rec_key.startswith("BK-"))

            # Verify all Recovery Key step buttons work without blocking
            panel.setup_copy_key_btn.click()
            self.assertIn("已复制", panel.setup_key_status_lbl.text())
            saved_txt = Path(td) / "saved-recovery-key.txt"
            panel._on_setup_save_txt(str(saved_txt))
            self.assertTrue(saved_txt.is_file())
            self.assertIn(rec_key, saved_txt.read_text(encoding="utf-8"))
            self.assertIn("已保存", panel.setup_key_status_lbl.text())
            panel.setup_finish_btn.click()
            self.assertEqual(panel.stack.currentIndex(), 2)

            # Verify category pills & multi-row wrap mode toggle
            self.assertGreaterEqual(len(panel._category_pill_widgets), 3)
            self.assertFalse(panel._cat_wrap_mode)
            panel._toggle_category_wrap_mode()
            self.assertTrue(panel._cat_wrap_mode)
            panel._toggle_category_wrap_mode()
            self.assertFalse(panel._cat_wrap_mode)

            # Verify category pill drag with floating avatar + placeholder slot
            first_pill = panel._category_pill_widgets[0]
            panel._on_category_pill_drag_start(first_pill, QPoint(200, 120), QPoint(16, 10))
            self.assertIsNotNone(panel._drag_avatar)
            self.assertTrue(first_pill._is_placeholder)
            panel._category_pill_widgets.append(panel._category_pill_widgets.pop(0))
            panel._on_category_pill_drag_finish(first_pill)
            self.assertIsNone(panel._drag_avatar)
            self.assertFalse(first_pill._is_placeholder)
            self.assertEqual(vault.get_categories()[-1]["id"], first_pill.cat_id)

            # Verify vertical bookmark card drag-and-drop reordering in UI
            cat0_id = vault.get_categories()[0]["id"]
            vault.add_bookmark("Drag Card 1", "https://drag1.example.com", category_id=cat0_id, pinned=False)
            vault.add_bookmark("Drag Card 2", "https://drag2.example.com", category_id=cat0_id, pinned=False)
            panel._select_category(cat0_id)
            self.assertGreaterEqual(len(panel._card_widgets), 2)
            last_card = panel._card_widgets[-1]
            second_last_card = panel._card_widgets[-2]
            panel._on_bookmark_card_drag_start(last_card, QPoint(220, 340), QPoint(30, 15))
            self.assertIsNotNone(panel._drag_avatar)
            self.assertTrue(last_card._is_placeholder)
            # Swap last two cards in _card_widgets and drop
            panel._card_widgets[-1], panel._card_widgets[-2] = (
                panel._card_widgets[-2],
                panel._card_widgets[-1],
            )
            panel._on_bookmark_card_drag_drop(last_card, QPoint(220, 260))
            self.assertIsNone(panel._drag_avatar)
            self.assertFalse(last_card._is_placeholder)
            saved_ids = [b["id"] for b in vault.get_bookmarks(category_id=cat0_id)]
            self.assertEqual(saved_ids[-2:], [last_card.bm_id, second_last_card.bm_id])

            # Verify Google Sheets / Clipboard batch paste in UI (Mode 1 & Mode 2)
            sheet_single_html = """
            <table>
                <tr><td><a href="https://single1.example.com">单列超链接 1</a></td></tr>
                <tr><td><a href="https://single2.example.com">单列超链接 2</a></td></tr>
            </table>
            """
            ok_p1 = panel._on_paste_clipboard_clicked(
                target_category_id=cat0_id,
                html_override=sheet_single_html,
                text_override="",
                auto_confirm_mode="single_category",
            )
            self.assertTrue(ok_p1)
            titles_cat0 = [b["title"] for b in vault.get_bookmarks(category_id=cat0_id)]
            self.assertIn("单列超链接 1", titles_cat0)
            self.assertIn("单列超链接 2", titles_cat0)

            sheet_multi_html = """
            <table>
                <tr><td>A列文件夹</td><td>B列文件夹</td></tr>
                <tr><td><a href="https://cola1.example.com">A列链接1</a></td><td><a href="https://colb1.example.com">B列链接1</a></td></tr>
                <tr><td><a href="https://cola2.example.com">A列链接2</a></td><td><a href="https://colb2.example.com">B列链接2</a></td></tr>
            </table>
            """
            ok_p2 = panel._on_paste_clipboard_clicked(
                html_override=sheet_multi_html,
                text_override="",
                auto_confirm_mode="matrix_headers",
            )
            self.assertTrue(ok_p2)
            ui_cat_names = [c["name"] for c in vault.get_categories()]
            self.assertIn("A列文件夹", ui_cat_names)
            self.assertIn("B列文件夹", ui_cat_names)


            # Lock vault -> page 1 (locked screen)
            panel.lock_vault()
            self.assertEqual(panel.stack.currentIndex(), 1)

            # Reset password with Recovery Key via inline recovery -> page 2 (unlocked)
            panel.recover_key_input.setText(rec_key)
            panel.recover_new_pwd.setText("RecoveredPass999")
            panel._handle_inline_recovery()
            self.assertTrue(vault.is_unlocked())
            self.assertEqual(panel.stack.currentIndex(), 2)

            # Verify FloatingWorldClock embeds bookmark_orb and scales proportionally
            clock = FloatingWorldClock({"world_clock": [], "alarms": [], "timer": {}})
            self.assertTrue(hasattr(clock, "bookmark_orb"))
            clock.resize(320, 120)
            clock._place_resize_handles()
            small_orb_w = clock.bookmark_orb.width()
            clock.resize(620, 260)
            clock._place_resize_handles()
            large_orb_w = clock.bookmark_orb.width()
            self.assertGreater(large_orb_w, small_orb_w)

            # Verify 问题 2: show_near_orb positions BookmarksFloatingPanel at the center of the screen
            clock.move(50, 50)
            clock.show()
            panel.show_near_orb(orb_widget=clock.bookmark_orb, anchor_window=clock)
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                expected_x = avail.left() + (avail.width() - panel.width()) // 2
                expected_y = avail.top() + (avail.height() - panel.height()) // 2
                self.assertAlmostEqual(panel.x(), expected_x, delta=20)
                self.assertAlmostEqual(panel.y(), expected_y, delta=20)

            clock.close()
            panel.close()



if __name__ == "__main__":
    unittest.main()
