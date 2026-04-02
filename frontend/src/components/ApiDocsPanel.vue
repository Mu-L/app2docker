<template>
  <div class="container-fluid px-0">
    <div class="alert alert-primary py-2 mb-3">
      <i class="fas fa-circle-info me-1"></i>
      接口认证支持 `Authorization: Bearer &lt;token&gt;` 或 `X-API-Key: &lt;appkey&gt;`
    </div>

    <ul class="nav nav-tabs mb-3">
      <li class="nav-item">
        <button
          class="nav-link"
          :class="{ active: activeTab === 'tasks' }"
          @click="activeTab = 'tasks'"
          type="button"
        >
          任务相关
        </button>
      </li>
      <li class="nav-item">
        <button
          class="nav-link"
          :class="{ active: activeTab === 'pipeline' }"
          @click="activeTab = 'pipeline'"
          type="button"
        >
          流水线相关
        </button>
      </li>
    </ul>

    <div v-if="activeTab === 'tasks'" class="card">
      <div class="card-header fw-semibold">任务接口（示例）</div>
      <div class="card-body">
        <div class="mb-3">
          <div class="small text-muted mb-1">获取任务列表</div>
          <code>GET /api/tasks</code>
        </div>
        <div class="mb-3">
          <div class="small text-muted mb-1">获取单个任务详情</div>
          <code>GET /api/tasks/{task_id}</code>
        </div>
        <div class="mb-3">
          <div class="small text-muted mb-1">停止任务</div>
          <code>POST /api/tasks/{task_id}/stop</code>
        </div>
        <div class="mb-0">
          <div class="small text-muted mb-1">删除任务</div>
          <code>DELETE /api/tasks/{task_id}</code>
        </div>
      </div>
    </div>

    <div v-else class="card">
      <div class="card-header fw-semibold">流水线接口（示例）</div>
      <div class="card-body">
        <div class="mb-3">
          <div class="small text-muted mb-1">获取流水线列表</div>
          <code>GET /api/pipelines</code>
        </div>
        <div class="mb-3">
          <div class="small text-muted mb-1">创建流水线</div>
          <code>POST /api/pipelines</code>
        </div>
        <div class="mb-3">
          <div class="small text-muted mb-1">更新流水线</div>
          <code>PUT /api/pipelines/{pipeline_id}</code>
        </div>
        <div class="mb-0">
          <div class="small text-muted mb-1">执行流水线</div>
          <code>POST /api/pipelines/{pipeline_id}/run</code>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";

const activeTab = ref("tasks");
</script>
