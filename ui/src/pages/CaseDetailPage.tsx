import { useParams } from 'react-router-dom'
import { CaseDetail } from '../components/cases/CaseDetail'

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>()
  if (!caseId) return null
  return <CaseDetail caseId={caseId} />
}
