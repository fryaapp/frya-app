import { useParams, useNavigate } from 'react-router-dom'
import { BelegDetail } from '../components/inbox/BelegDetail'

export function BelegDetailPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  if (!caseId) return null
  return <BelegDetail caseId={caseId} onClose={() => navigate(-1)} />
}
