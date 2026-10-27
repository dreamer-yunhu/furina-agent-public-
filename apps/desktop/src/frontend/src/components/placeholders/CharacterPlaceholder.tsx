// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：这是工作台内的角色槽位占位，不是独立角色窗口。

interface CharacterPlaceholderProps {
  src?: string
}

export function CharacterPlaceholder({ src }: CharacterPlaceholderProps) {
  return (
    <div className="character-placeholder">
      {src ? (
        <img className="character-placeholder__image" src={src} alt="" />
      ) : (
        <div className="character-placeholder__frame" aria-hidden="true">
          F4
        </div>
      )}
      <div className="character-placeholder__copy">
        <strong>角色槽位</strong>
        <span>独立窗口 / Live2D 在 F4 评估</span>
      </div>
    </div>
  )
}
