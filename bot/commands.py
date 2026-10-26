from .models import IncomingMessage

HELP_TEXT = """可用命令：
#persona <名称>  切换当前会话人设
#personas        查看可用人设
#reset           清空当前会话上下文
#id              查看当前会话 ID
#reminders       查看待提醒（定时/条件）
#proactive       查看主动消息任务
#doc             文档处理（PDF/Word）
#pause           暂停自动回复/主动消息
#resume          恢复
#cancel <编号>   取消提醒
#cancel all      取消全部提醒
#help            显示本帮助"""


class CommandMixin:
    def _parse_command(self, message: IncomingMessage) -> list[str] | None:
        text = message.content.strip()
        if not text.startswith("#"):
            return None
        parts = text[1:].strip().split()
        if not parts:
            return None
        public = {
            "id", "会话id", "会话", "help", "帮助",
            "reminders", "提醒", "提醒列表", "cancel", "取消",
            "proactive", "主动", "主动列表",
            "doc", "文档",
        }
        if parts[0].lower() in public:
            return parts
        if message.sender_id not in self.settings.admin_wxids:
            return None
        return parts

    def _handle_command(self, message: IncomingMessage, parts: list[str]) -> None:
        name = parts[0].lower()
        if name in {"help", "帮助"}:
            self._send(message.session_key, HELP_TEXT, split=False)
            return

        if name in {"personas", "人设列表"}:
            current = self.registry.resolve(message.session_key, self.store.get_persona_key(message.session_key))
            self._send(
                message.session_key,
                f"当前人设：{current.key} ({current.display_name})\n\n{self.registry.describe()}",
                split=False,
            )
            return

        if name in {"persona", "人设"}:
            if len(parts) < 2:
                current = self.registry.resolve(message.session_key, self.store.get_persona_key(message.session_key))
                self._send(
                    message.session_key,
                    f"当前人设：{current.key} ({current.display_name})\n\n{self.registry.describe()}",
                    split=False,
                )
                return
            key = parts[1]
            persona = self.registry.get(key)
            if persona is None:
                self._send(
                    message.session_key,
                    f"没有名为 {key} 的人设。\n\n{self.registry.describe()}",
                    split=False,
                )
                return
            self.store.set_persona_key(message.session_key, key)
            self._send(message.session_key, f"已切换为 {persona.display_name} ({persona.key})")
            return

        if name in {"reset", "重置"}:
            self.store.clear_session(message.session_key)
            self._send(message.session_key, "当前会话的上下文已清空")
            return

        if name in {"reminders", "提醒", "提醒列表"}:
            rows = self.reminder_store.list_pending(message.session_key)
            if not rows:
                self._send(message.session_key, "现在没有待提醒的事")
                return
            lines = ["待提醒："]
            for row in rows:
                if row["kind"] == "condition":
                    interval = row["check_interval_minutes"] or self.settings.condition_interval_minutes
                    lines.append(f"#{row['id']} 条件 {row['condition_text']}（每 {interval} 分钟检查）")
                else:
                    lines.append(f"#{row['id']} 定时 {row['due_at']} {row['content'] or '到点了'}")
            self._send(message.session_key, "\n".join(lines), split=False)
            return

        if name in {"proactive", "主动", "主动列表"}:
            if not self.settings.proactive_enabled:
                self._send(message.session_key, "主动消息已关闭")
                return
            self._send(
                message.session_key,
                "主动消息默认开启，只发给主动发送白名单里的私聊。"
                "按最近一条聊天时间算，"
                f"安静时段 {self.settings.proactive_quiet_start:g} 点到 "
                f"{self.settings.proactive_quiet_end:g} 点，"
                f"随机 {self.settings.proactive_min_minutes}-"
                f"{self.settings.proactive_max_minutes} 分钟。",
                split=False,
            )
            return

        if name in {"doc", "文档"}:
            self._handle_doc_command(message, parts)
            return

        if name in {"cancel", "取消"}:
            if len(parts) < 2:
                self._send(message.session_key, "用法：#cancel 编号，或 #cancel all")
                return
            target = parts[1].strip().lower()
            if target in {"all", "全部", "所有", "一切"}:
                count = self.reminder_store.cancel_all(message.session_key)
                if count:
                    self._send(message.session_key, f"好，已取消 {count} 条提醒")
                else:
                    self._send(message.session_key, "现在没有待提醒的事")
                return
            try:
                reminder_id = int(target)
            except ValueError:
                self._send(message.session_key, "编号要是数字，比如 #cancel 3")
                return
            if self.reminder_store.cancel(message.session_key, reminder_id):
                self._send(message.session_key, f"已取消 #{reminder_id}")
            else:
                self._send(message.session_key, f"没找到待提醒的 #{reminder_id}")
            return

        if name in {"id", "会话id", "会话"}:
            self._send(message.session_key, f"当前会话 ID：{message.session_key}")
            return

        self._send(message.session_key, HELP_TEXT, split=False)
