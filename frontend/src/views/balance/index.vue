<template>
  <section class="page" data-module="balance">
    <header class="page-head">
      <div>
        <h2>采集流量均衡管理</h2>
        <p class="page-desc">维护流量均衡的算法选择、扩缩容阈值与权重配置；策略字段与状态同单保存，执行结果只反映实际生效版本。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记均衡策略</button>
        <button class="btn" type="button" @click="exportRows">导出采集流量均衡清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>策略编号</span>
        <input v-model="keyword" placeholder="按策略编号检索" />
      </label>
      <label class="filter-item">
        <span>策略状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '策略状态'">
              <span :class="['status-tag', statusClass(String(row.status))]">{{ row.status }}</span>
            </template>
            <template v-else-if="column === '策略版本'">v{{ row.策略版本 ?? 1 }}</template>
            <template v-else-if="column === '冲突/停用依据'">
              <span class="reason-text">{{ row.等待原因 || row.停用依据 || '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button class="link" type="button" :disabled="row.status === '已关闭'" @click="openEdit(row)">编辑保存</button>
            <button
              v-for="action in availableActions(String(row.status))"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集流量均衡数据，可先登记均衡策略</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集流量均衡记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="result-block">
      <header class="block-head">
        <h3>均衡执行结果明细（驱动节点巡检负载视图）</h3>
        <button class="btn ghost" type="button" @click="loadExecutions">刷新执行结果</button>
      </header>
      <p class="page-desc">数据只来自实际生效策略版本；已关闭策略不产生任何建议，刷新页面后旧阈值不会残留。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in executionColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in executions" :key="String(item.id)">
            <td v-for="column in executionColumns" :key="column">{{ item[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!executions.length">
            <td :colspan="executionColumns.length" class="empty-state">当前没有实际生效的均衡策略，暂无执行结果</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 登记 / 编辑弹窗：字段与状态在同一表单一起提交 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <h3>{{ formMode === 'create' ? '登记均衡策略' : `编辑保存：${form.策略编号 || ''}` }}</h3>
        <div class="form-grid">
          <label v-for="field in formFields" :key="field.name" class="form-item">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input v-if="field.type !== 'select'" v-model="form[field.name]" :placeholder="field.placeholder" />
            <select v-else v-model="form[field.name]">
              <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
            </select>
          </label>
          <label class="form-item">
            <span>策略状态（与字段一起保存）</span>
            <select v-model="form.status" :disabled="formMode === 'create'">
              <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
        </div>
        <p v-if="formMode === 'edit'" class="page-desc">保存已生效策略的字段会自动发布新版本，执行结果与巡检负载视图立即切换到新版本阈值。</p>
        <footer class="modal-foot">
          <span v-if="formError" class="error-text">{{ formError }}</span>
          <button class="btn ghost" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="button" @click="submitForm">保存</button>
        </footer>
      </div>
    </div>

    <!-- 详情抽屉：列表页与详情页同源，刷新后阈值一致 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal modal-wide">
        <h3>均衡策略详情</h3>
        <dl v-if="detail" class="detail-list">
          <template v-for="entry in detailRows" :key="entry.label">
            <dt>{{ entry.label }}</dt>
            <dd>{{ entry.value ?? '—' }}</dd>
          </template>
        </dl>
        <footer class="modal-foot">
          <button class="btn primary" type="button" @click="closeDetail">关闭</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
interface FormState {
  id: number | null
  策略编号: string
  负载算法: string
  权重因子: string
  扩容阈值: string
  缩容阈值: string
  最小节点: string
  最大节点: string
  节点集合: string
  优先级: string
  冲突处理方式: string
  status: string
}

const ENDPOINT = '/api/balance'
const columns = ['策略编号', '策略版本', '策略状态', '节点集合', '负载算法', '权重因子', '扩容阈值', '缩容阈值', '优先级', '冲突处理方式', '冲突/停用依据']
const executionColumns = ['节点编号', '策略编号', '策略版本', '生效范围', '负载算法', '权重因子', '扩容阈值', '缩容阈值', '扩缩容建议', '数据来源']
const statuses = ['草稿', '已生效', '已暂停', '已关闭']
const actionMap: Record<string, string[]> = {
  草稿: ['启用策略', '关闭策略'],
  已生效: ['暂停策略', '关闭策略'],
  已暂停: ['启用策略', '关闭策略'],
  已关闭: [],
}

const formFields = [
  { name: '策略编号', label: '策略编号', required: true, type: 'input', placeholder: '如 BALA-0006' },
  { name: '负载算法', label: '负载算法', required: true, type: 'input', placeholder: '如 加权轮询' },
  { name: '权重因子', label: '权重因子', required: true, type: 'input', placeholder: '数值' },
  { name: '扩容阈值', label: '扩容阈值(%)', required: true, type: 'input', placeholder: '如 75' },
  { name: '缩容阈值', label: '缩容阈值(%)', required: true, type: 'input', placeholder: '如 25' },
  { name: '最小节点', label: '最小节点', required: false, type: 'input', placeholder: '数值' },
  { name: '最大节点', label: '最大节点', required: false, type: 'input', placeholder: '数值' },
  { name: '节点集合', label: '节点集合（顿号分隔）', required: true, type: 'input', placeholder: 'NODE-0001、NODE-0002' },
  { name: '优先级', label: '优先级', required: false, type: 'input', placeholder: '数值，越大优先级越高' },
  { name: '冲突处理方式', label: '冲突处理方式', required: false, type: 'select', options: ['显式发布优先级', '较新策略版本'] },
] as const

const emptyForm = (): FormState => ({
  id: null,
  策略编号: '',
  负载算法: '',
  权重因子: '',
  扩容阈值: '',
  缩容阈值: '',
  最小节点: '',
  最大节点: '',
  节点集合: '',
  优先级: '',
  冲突处理方式: '较新策略版本',
  status: '草稿',
})

const rows = ref<Row[]>([])
const executions = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const form = ref<FormState>(emptyForm())
const formError = ref('')

const detailVisible = ref(false)
const detail = ref<Row | null>(null)

const stats = computed(() => [
  { label: '均衡策略总数', value: rows.value.length },
  { label: '已生效策略', value: rows.value.filter((r) => r.status === '已生效').length },
  { label: '覆盖冲突等待', value: rows.value.filter((r) => Boolean(r.等待原因)).length },
  { label: '已关闭策略', value: rows.value.filter((r) => r.status === '已关闭').length },
])

const detailRows = computed(() => {
  if (!detail.value) return []
  const row = detail.value
  return [
    { label: '策略编号', value: row.策略编号 },
    { label: '当前策略版本', value: `v${row.策略版本 ?? 1}` },
    { label: '策略状态', value: row.status },
    { label: '唯一生效范围（节点集合）', value: row.节点集合 },
    { label: '负载算法', value: row.负载算法 },
    { label: '权重因子', value: row.权重因子 },
    { label: '扩容阈值', value: row.扩容阈值 },
    { label: '缩容阈值', value: row.缩容阈值 },
    { label: '优先级', value: row.优先级 },
    { label: '冲突处理方式', value: row.冲突处理方式 },
    { label: '覆盖冲突等待原因', value: row.等待原因 },
    { label: '停用依据', value: row.停用依据 },
  ]
})

function availableActions(status: string): string[] {
  return actionMap[status] ?? []
}

function statusClass(status: string): string {
  return { 已生效: 'tag-active', 草稿: 'tag-draft', 已暂停: 'tag-paused', 已关闭: 'tag-closed' }[status] ?? ''
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  formMode.value = 'create'
  form.value = emptyForm()
  formError.value = ''
  formVisible.value = true
}

function openEdit(row: Row) {
  formMode.value = 'edit'
  form.value = {
    id: Number(row.id),
    策略编号: String(row.策略编号 ?? ''),
    负载算法: String(row.负载算法 ?? ''),
    权重因子: String(row.权重因子 ?? ''),
    扩容阈值: String(row.扩容阈值 ?? ''),
    缩容阈值: String(row.缩容阈值 ?? ''),
    最小节点: String(row.最小节点 ?? ''),
    最大节点: String(row.最大节点 ?? ''),
    节点集合: String(row.节点集合 ?? ''),
    优先级: String(row.优先级 ?? ''),
    冲突处理方式: String(row.冲突处理方式 ?? '较新策略版本'),
    status: String(row.status ?? '草稿'),
  }
  formError.value = ''
  formVisible.value = true
}

function closeForm() {
  formVisible.value = false
}

function closeDetail() {
  detailVisible.value = false
}

function openDetail(row: Row) {
  detail.value = row
  detailVisible.value = true
}

async function submitForm() {
  formError.value = ''
  const values: Record<string, string> = { ...form.value } as unknown as Record<string, string>
  delete (values as Record<string, unknown>).id
  try {
    const url = formMode.value === 'create' ? ENDPOINT : `${ENDPOINT}/${form.value.id}`
    const method = formMode.value === 'create' ? 'POST' : 'PUT'
    const response = await request(url, { method, body: JSON.stringify({ values }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      formError.value = payload.message || '保存失败，字段与状态未写入'
      return
    }
    formVisible.value = false
    await reload()
    await loadExecutions()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '均衡策略保存失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 冲突失败或终态拦截：服务端会保持原状态，直接展示原因并重新取数。
      errorMessage.value = payload.message || '采集流量均衡动作未生效'
      await reload()
      await loadExecutions()
      return
    }
    await reload()
    await loadExecutions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集流量均衡操作失败'
  }
}

async function loadExecutions() {
  try {
    const response = await request(`${ENDPOINT}/executions`)
    if (!response.ok) throw new Error('均衡执行结果读取失败')
    const payload = await response.json()
    executions.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '均衡执行结果读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('均衡策略列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集流量均衡列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadExecutions()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.status-tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.tag-active { background: #dcfae6; color: #027a48; }
.tag-draft { background: #eef2f6; color: #475467; }
.tag-paused { background: #fef0c7; color: #b54708; }
.tag-closed { background: #fee4e2; color: #b42318; }
.reason-text { color: var(--muted); font-size: 12px; }
.result-block { margin-top: 20px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.block-head { display: flex; justify-content: space-between; align-items: center; }
.block-head h3 { margin: 0; font-size: 15px; }
.modal-mask { position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 640px; max-height: 86vh; overflow: auto; }
.modal-wide { width: 720px; }
.modal h3 { margin: 0 0 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input, .form-item select { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; align-items: center; }
.modal-foot .error-text { margin-right: auto; }
.detail-list { display: grid; grid-template-columns: 160px 1fr; row-gap: 8px; margin: 0; }
.detail-list dt { color: var(--muted); font-size: 13px; }
.detail-list dd { margin: 0; font-size: 13px; }
.link:disabled { color: var(--muted); cursor: not-allowed; }
</style>
