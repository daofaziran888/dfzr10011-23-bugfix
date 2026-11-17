<template>
  <section class="page" data-module="nodecheck">
    <header class="page-head">
      <div>
        <h2>节点状态巡检管理</h2>
        <p class="page-desc">维护节点状态的资源指标与采样；节点巡检负载视图读取均衡执行结果，只反映实际生效策略的当前版本与唯一生效范围。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检记录</button>
        <button class="btn" type="button" @click="exportRows">导出节点状态巡检清单</button>
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
        <span>记录编号</span>
        <input v-model="keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>巡检状态</span>
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
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
          <td :colspan="columns.length + 1" class="empty-state">暂无节点状态巡检数据，可先登记巡检记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条节点状态巡检记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="result-block">
      <header class="block-head">
        <h3>节点巡检负载视图</h3>
        <button class="btn ghost" type="button" @click="loadAll">刷新视图</button>
      </header>
      <p class="page-desc">取数来源：{{ loadView.source || '均衡执行结果' }}。页面不保存阈值副本，阈值一律来自实际生效策略版本；已关闭策略不会在此出现。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in loadColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in loadView.items" :key="String(displayKey(item, '节点编号')) + '-' + String(displayKey(item, '策略编号'))">
            <td v-for="column in loadColumns" :key="column">{{ item[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!loadView.items.length">
            <td :colspan="loadColumns.length" class="empty-state">暂无实际生效的均衡策略覆盖节点，负载视图为空</td>
          </tr>
        </tbody>
      </table>
      <div v-if="loadView.waiting_conflicts?.length" class="waiting-box">
        <strong>覆盖冲突等待策略：</strong>
        <ul>
          <li v-for="w in loadView.waiting_conflicts" :key="String(displayKey(w, '策略编号'))">
            {{ w.策略编号 }}（{{ w.策略版本 }}，覆盖 {{ joinNodes(w.节点集合) }}）：{{ w.等待原因 }}
          </li>
        </ul>
      </div>
    </section>

    <section class="result-block">
      <header class="block-head">
        <h3>修复均衡策略状态汇总清单</h3>
      </header>
      <p class="page-desc">按既有取数逻辑定位策略当前状态，与均衡模块列表、详情及其他业务页面同源；「实际生效」标记取自均衡执行结果。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in summaryColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in summary" :key="String(item.id)">
            <td v-for="column in summaryColumns" :key="column">
              <template v-if="column === '实际生效'">
                <span :class="['status-tag', item.实际生效 ? 'tag-active' : 'tag-draft']">
                  {{ item.实际生效 ? '生效中' : '未生效' }}
                </span>
              </template>
              <template v-else-if="column === '节点集合'">{{ joinNodes(item.节点集合) }}</template>
              <template v-else>{{ item[column] ?? '—' }}</template>
            </td>
          </tr>
          <tr v-if="!summary.length">
            <td :colspan="summaryColumns.length" class="empty-state">暂无均衡策略状态记录</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | string[] | null>

function joinNodes(value: Row[keyof Row]): string {
  return Array.isArray(value) ? value.join('、') : String(value ?? '')
}

function displayKey(item: Row, field: string): string | number {
  const value = item[field]
  return typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
}

const ENDPOINT = '/api/nodecheck'
const columns = ['记录编号', '节点编号', 'CPU使用率', '内存使用率', '磁盘使用率', '网络延迟', '错误次数', '采样时间']
const actions = ['标记异常', '隔离节点', '恢复节点']
const statuses = ['正常', '亚健康', '异常', '已下线']
const loadColumns = ['节点编号', '策略编号', '策略版本', '唯一生效范围', '扩容阈值', '缩容阈值', '权重因子', 'CPU使用率', '巡检状态', '扩缩容建议', '冲突处理方式', '数据来源']
const summaryColumns = ['策略编号', '策略版本', '状态', '实际生效', '节点集合', '扩容阈值', '缩容阈值', '权重因子', '冲突处理方式', '等待原因', '停用依据']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const loadView = ref<{ items: Row[]; total: number; source: string; waiting_conflicts: Row[] }>({
  items: [], total: 0, source: '均衡执行结果', waiting_conflicts: [],
})
const summary = ref<Row[]>([])

const stats = ref([
  { label: '巡检记录总数', value: 0 },
  { label: '异常记录', value: 0 },
  { label: '负载视图节点', value: 0 },
  { label: '实际生效策略', value: 0 },
])

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡检记录登记入口尚未接入审批流，可调用 POST /api/nodecheck 接口登记'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '节点状态巡检动作未生效')
    await reload()
    await loadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '节点状态巡检操作失败'
  }
}

async function loadLoadView() {
  const response = await request(`${ENDPOINT}/node-load-view`)
  if (!response.ok) throw new Error('节点巡检负载视图读取失败')
  loadView.value = await response.json()
}

async function loadSummary() {
  const response = await request(`${ENDPOINT}/repair-balance-summary`)
  if (!response.ok) throw new Error('修复均衡策略状态清单读取失败')
  const payload = await response.json()
  summary.value = payload.items ?? []
}

async function loadAll() {
  errorMessage.value = ''
  try {
    await Promise.all([loadLoadView(), loadSummary()])
    stats.value = [
      { label: '巡检记录总数', value: rows.value.length },
      { label: '异常记录', value: rows.value.filter((r) => r.status === '异常' || r.status === '亚健康').length },
      { label: '负载视图节点', value: loadView.value.total },
      { label: '实际生效策略', value: summary.value.filter((r) => r.实际生效).length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检负载数据读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('巡检记录列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '节点状态巡检列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.result-block { margin-top: 20px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.block-head { display: flex; justify-content: space-between; align-items: center; }
.block-head h3 { margin: 0; font-size: 15px; }
.status-tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.tag-active { background: #dcfae6; color: #027a48; }
.tag-draft { background: #eef2f6; color: #475467; }
.waiting-box { margin-top: 10px; padding: 10px 12px; background: #fffaeb; border: 1px solid #fedf89; border-radius: 8px; font-size: 13px; }
.waiting-box ul { margin: 6px 0 0; padding-left: 18px; }
</style>
