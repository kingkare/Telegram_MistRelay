import { defineStore } from 'pinia'
import {
  browseTelegramDrive,
  isTelegramDriveFile,
  isTelegramDriveFolder,
  type TelegramDriveFolder,
  type TelegramDriveItem,
} from '@/api'

interface MediaGroupCrumb {
  mediaGroupId: string
  name: string
}

interface PcDriveState {
  items: TelegramDriveItem[]
  loading: boolean
  error: string
  page: number
  pageSize: number
  total: number
  search: string
  typeFilter: string
  sortBy: string
  sortDesc: boolean
  currentMediaGroupId: string
  currentFolderName: string
  mediaGroupStack: MediaGroupCrumb[]
}

export const usePcDriveStore = defineStore('pcDrive', {
  state: (): PcDriveState => ({
    items: [],
    loading: false,
    error: '',
    page: 1,
    pageSize: 40,
    total: 0,
    search: '',
    typeFilter: '',
    sortBy: 'message_date',
    sortDesc: true,
    currentMediaGroupId: '',
    currentFolderName: '',
    mediaGroupStack: [],
  }),
  getters: {
    isInsideMediaGroup: (state) => Boolean(state.currentMediaGroupId),
    totalPages: (state) => Math.max(1, Math.ceil(state.total / state.pageSize)),
    queryParams: (state) => ({
      page: state.page,
      page_size: state.pageSize,
      search: state.search || undefined,
      type: state.typeFilter || undefined,
      sort_by: state.sortBy,
      sort_desc: state.sortDesc,
      media_group_id: state.currentMediaGroupId || undefined,
    }),
  },
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const response = await browseTelegramDrive(this.queryParams)
        if (!response.success) {
          throw new Error(response.error || '加载网盘失败')
        }
        this.items = this.currentMediaGroupId
          ? response.items.filter(isTelegramDriveFile)
          : response.items
        this.total = response.total
        this.page = response.page
        this.pageSize = response.page_size
      } catch (error: any) {
        this.error = error.response?.data?.error || error.message || '加载网盘失败'
        this.items = []
        this.total = 0
        throw error
      } finally {
        this.loading = false
      }
    },

    refresh() {
      return this.load()
    },

    setSearch(value: string) {
      this.search = value.trim()
      this.page = 1
      return this.load()
    },

    setTypeFilter(value: string) {
      this.typeFilter = value
      this.page = 1
      return this.load()
    },

    resetFilters() {
      this.search = ''
      this.typeFilter = ''
      this.page = 1
      return this.load()
    },

    setSort(sortBy: string, sortDesc: boolean) {
      this.sortBy = sortBy
      this.sortDesc = sortDesc
      this.page = 1
      return this.load()
    },

    setPage(page: number) {
      this.page = Math.max(1, page)
      return this.load()
    },

    setPageSize(pageSize: number) {
      this.pageSize = Math.max(1, pageSize)
      this.page = 1
      return this.load()
    },

    enterMediaGroup(folder: TelegramDriveFolder) {
      if (!isTelegramDriveFolder(folder)) return Promise.resolve()
      this.currentMediaGroupId = folder.media_group_id
      this.currentFolderName = folder.file_name || folder.media_group_id
      this.mediaGroupStack = [{
        mediaGroupId: folder.media_group_id,
        name: this.currentFolderName,
      }]
      this.search = ''
      this.typeFilter = ''
      this.page = 1
      return this.load()
    },

    leaveMediaGroup() {
      this.currentMediaGroupId = ''
      this.currentFolderName = ''
      this.mediaGroupStack = []
      this.page = 1
      return this.load()
    },
  },
})
