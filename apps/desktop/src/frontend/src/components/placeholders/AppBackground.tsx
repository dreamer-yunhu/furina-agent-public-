// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：没有美术资源时给中性背景；不要在这里画死最终视觉风格。

interface AppBackgroundProps {
  src?: string
}

export function AppBackground({ src }: AppBackgroundProps) {
  if (!src) {
    return <div className="app-background app-background--fallback" />
  }

  return <div className="app-background" style={{ backgroundImage: `url("${src}")` }} />
}
