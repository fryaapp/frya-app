export interface FileStatus {
  name: string
  size: number
  status: 'pending' | 'uploading' | 'processing' | 'done' | 'error' | 'duplicate'
  error?: string
}
