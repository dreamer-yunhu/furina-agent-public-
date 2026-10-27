// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：角色入口保持小巧，不占用中央工作区；独立窗口属于 F4。

interface CharacterPlaceholderProps {
  src?: string
}

export function CharacterPlaceholder({ src }: CharacterPlaceholderProps) {
  return (
    <div className="character-avatar" title="角色窗口占位 · 独立窗口在 F4 评估">
      {src ? (
        <img className="character-avatar__image" src={src} alt="角色" />
      ) : (
        <span aria-hidden="true">芙</span>
      )}
    </div>
  )
}
