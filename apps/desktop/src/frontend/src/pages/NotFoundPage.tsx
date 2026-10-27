// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import { Link } from '../app/Link'
import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'

export function NotFoundPage() {
  return (
    <div className="page">
      <PageHeader
        title="页面不存在"
        description="当前地址没有对应的前端路由。"
      />
      <EmptyState
        title="找不到这个页面"
        description="检查地址，或返回对话页继续。"
      />
      <div className="page__actions">
        <Link className="button button--primary" to="/chat">
          返回对话
        </Link>
      </div>
    </div>
  )
}
