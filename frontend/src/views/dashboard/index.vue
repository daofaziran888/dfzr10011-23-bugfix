<template>
  <section class="page" data-module="dashboard">
    <header class="page-head">
      <div>
        <h2>全局采集看板管理</h2>
        <p class="page-desc">维护全局看板的指标配置、刷新策略与告警联动，为全局采集看板提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记看板面板</button>
        <button class="btn" type="button" @click="exportRows">导出全局采集看板清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
          <td :colspan="columns.length + 1" class="empty-state">暂无全局采集看板数据，可先登记看板面板</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条全局采集看板记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="result-block">
      <header class="block-head">
        <h3>均衡策略同步面板（与节点状态巡检模块同源）</h3>
        <button class="btn ghost" type="button" @click="loadBalanceData">刷新均衡数据</button>
      </header>
      <p class="page-desc">同步采用巡检模块的修复均衡策略状态清单与均衡执行结果数据，页面不做二次计算，阈值只认实际生效版本。</p>

      <h4 class="sub-title">修复均衡策略状态汇总清单</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in summaryColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in balanceSummary" :key="String(item.id)">
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
          <tr v-if="!balanceSummary.length">
            <td :colspan="summaryColumns.length" class="empty-state">暂无均衡策略状态记录</td>
          </tr>
        </tbody>
      </table>

      <h4 class="sub-title">均衡执行结果（节点级扩缩容建议）</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in executionColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in balanceExecutions" :key="String(item.id)">
            <td v-for="column in executionColumns" :key="column">{{ item[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!balanceExecutions.length">
            <td :colspan="executionColumns.length" class="empty-state">当前无实际生效策略，执行结果为空</td>
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

const ENDPOINT = '/api/dashboard'
const columns = ["面板编号", "面板名称", "显示指标", "刷新间隔", "告警配置", "数据范围", "创建人", "面板状态"]
const actions = ["启用面板", "暂停面板", "归档面板"]
const statuses = ["草稿", "已启用", "已暂停", "已归档"]
const stats = [{"label": "看板面板总数", "value": 0}, {"label": "已启用面板", "value": 0}, {"label": "已暂停面板", "value": 0}]
const summaryColumns = ['策略编号', '策略版本', '状态', '实际生效', '节点集合', '扩容阈值', '缩容阈值', '停用依据']
const executionColumns = ['节点编号', '策略编号', '策略版本', '生效范围', '扩容阈值', '缩容阈值', '扩缩容建议', '数据来源']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const balanceSummary = ref<Row[]>([])
const balanceExecutions = ref<Row[]>([])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '看板面板登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '全局采集看板动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '全局采集看板操作失败'
  }
}

async function loadBalanceData() {
  errorMessage.value = ''
  try {
    const [summaryResp, executionResp] = await Promise.all([
      request('/api/nodecheck/repair-balance-summary'),
      request('/api/balance/executions'),
    ])
    if (!summaryResp.ok || !executionResp.ok) throw new Error('均衡同步数据读取失败')
    const summaryPayload = await summaryResp.json()
    const executionPayload = await executionResp.json()
    balanceSummary.value = summaryPayload.items ?? []
    balanceExecutions.value = executionPayload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '均衡同步数据读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('看板面板列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '全局采集看板列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadBalanceData()
})
</script>

<style scoped>
.result-block { margin-top: 20px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.block-head { display: flex; justify-content: space-between; align-items: center; }
.block-head h3 { margin: 0; font-size: 15px; }
.sub-title { font-size: 14px; margin: 14px 0 6px; }
.status-tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.tag-active { background: #dcfae6; color: #027a48; }
.tag-draft { background: #eef2f6; color: #475467; }
</style>
