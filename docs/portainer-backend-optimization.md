# Portainer 后端技术改动方案

## 一、核心问题分析

### 1.1 API文档对比发现的问题

基于 `docs/portainer-api.md` 文档分析,发现以下关键问题:

| 问题 | 严重程度 | 影响 |
|------|----------|------|
| 容器创建API不存在 | 🔴 P0 | Docker Run模式完全不可用 |
| Stack创建缺少type参数 | 🔴 P0 | Stack创建失败或405错误 |
| Stack更新缺少Prune参数 | 🟡 P1 | 可能导致意外行为 |
| 缺少Stack管理API | 🟡 P1 | 无法获取Stack列表和详情 |

### 1.2 根本原因

**Portainer 2.33.3 版本不支持直接创建容器**,必须通过Stack API进行部署。当前代码使用了不存在的容器创建API,导致Docker Run模式失败。

---

## 二、技术改动方案

### 改动1: 修复 PortainerClient API

#### 文件位置
`backend/portainer_client.py`

#### 改动内容

**1. 删除 `deploy_container` 方法**

```python
# ❌ 删除这个方法 - 使用了不存在的API
# def deploy_container(self, ...):
#     # POST /docker/containers/create  ← 这个API在Portainer 2.33.3中返回404
#     pass
```

**2. 新增 `deploy_container_as_stack` 方法**

```python
def deploy_container_as_stack(self, container_name: str, image: str, 
                              ports: list = None, env: list = None, 
                              volumes: list = None, restart_policy: str = "always"):
    """
    通过创建单容器Stack来部署容器
    
    Args:
        container_name: 容器名称
        image: 镜像名称
        ports: 端口映射列表 [{"container_port": 80, "host_port": 8080}]
        env: 环境变量列表 ["KEY=value"]
        volumes: 卷挂载列表 ["/host/path:/container/path"]
        restart_policy: 重启策略
    
    Returns:
        dict: 部署结果
    """
    # 生成 docker-compose.yml 内容
    compose_content = self._generate_single_container_compose(
        container_name, image, ports, env, volumes, restart_policy
    )
    
    # 使用 Stack API 部署
    return self.deploy_stack(container_name, compose_content, env)

def _generate_single_container_compose(self, container_name: str, image: str,
                                       ports: list = None, env: list = None,
                                       volumes: list = None, restart_policy: str = "always"):
    """生成单容器的 docker-compose.yml 内容"""
    
    service = {
        "image": image,
        "restart": restart_policy
    }
    
    # 添加端口映射
    if ports:
        service["ports"] = [
            f"{p['host_port']}:{p['container_port']}" 
            for p in ports
        ]
    
    # 添加环境变量
    if env:
        service["environment"] = env
    
    # 添加卷挂载
    if volumes:
        service["volumes"] = volumes
    
    compose = {
        "version": "3.8",
        "services": {
            container_name: service
        }
    }
    
    import yaml
    return yaml.dump(compose, default_flow_style=False)
```

**3. 修复 `deploy_stack` 方法**

```python
def deploy_stack(self, stack_name: str, compose_content: str, env: list = None):
    """
    创建或更新 Stack
    
    Args:
        stack_name: Stack 名称
        compose_content: docker-compose.yml 内容
        env: 环境变量列表 ["KEY=value"]
    
    Returns:
        dict: 部署结果
    """
    # 检查 Stack 是否存在
    existing_stack = self.get_stack_by_name(stack_name)
    
    if existing_stack:
        # 更新已有 Stack
        return self.update_stack(existing_stack["Id"], compose_content, env)
    else:
        # 创建新 Stack - ⚠️ 必须添加 type=2
        url = f"{self.base_url}/api/stacks"
        params = {
            "endpointId": self.endpoint_id,
            "type": 2,  # ⚠️ 必须添加 - Stack类型 (2 = Compose)
            "method": "string"
        }
        
        data = {
            "Name": stack_name,
            "StackFileContent": compose_content,
            "Env": self._format_env(env)
        }
        
        response = requests.post(url, headers=self.headers, params=params, json=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"创建Stack失败: {response.text}")

def update_stack(self, stack_id: int, compose_content: str, env: list = None):
    """
    更新已有 Stack
    
    Args:
        stack_id: Stack ID
        compose_content: docker-compose.yml 内容
        env: 环境变量列表
    
    Returns:
        dict: 更新结果
    """
    url = f"{self.base_url}/api/stacks/{stack_id}"
    
    # ⚠️ 必须添加 Prune 参数
    update_config = {
        "StackFileContent": compose_content,
        "Env": self._format_env(env),
        "Prune": False  # ⚠️ 必须添加 - 不清理未使用的资源
    }
    
    response = requests.put(url, headers=self.headers, json=update_config)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"更新Stack失败: {response.text}")

def _format_env(self, env: list = None):
    """格式化环境变量为Portainer格式"""
    if not env:
        return []
    
    return [{"name": e.split("=")[0], "value": e.split("=")[1]} 
            for e in env if "=" in e]
```

**4. 新增 Stack 管理方法**

```python
def list_stacks(self):
    """
    获取所有 Stack 列表
    
    Returns:
        list: Stack 列表
        [
            {
                "Id": 18,
                "Name": "my-app",
                "Status": 1,  # 1=运行中, 0=已停止
                "Type": 2,
                "EndpointId": 1,
                "CreationDate": 1234567890,
                "UpdateDate": 1234567890
            }
        ]
    """
    url = f"{self.base_url}/api/stacks"
    params = {"endpointId": self.endpoint_id}
    
    response = requests.get(url, headers=self.headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"获取Stack列表失败: {response.text}")

def get_stack(self, stack_id: int):
    """
    获取 Stack 详情
    
    Args:
        stack_id: Stack ID
    
    Returns:
        dict: Stack 详情
    """
    url = f"{self.base_url}/api/stacks/{stack_id}"
    
    response = requests.get(url, headers=self.headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"获取Stack详情失败: {response.text}")

def get_stack_by_name(self, stack_name: str):
    """
    根据名称获取 Stack
    
    Args:
        stack_name: Stack 名称
    
    Returns:
        dict: Stack 信息 或 None
    """
    stacks = self.list_stacks()
    for stack in stacks:
        if stack["Name"] == stack_name:
            return stack
    return None

def start_stack(self, stack_id: int):
    """启动 Stack"""
    url = f"{self.base_url}/api/stacks/{stack_id}/start"
    response = requests.post(url, headers=self.headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"启动Stack失败: {response.text}")

def stop_stack(self, stack_id: int):
    """停止 Stack"""
    url = f"{self.base_url}/api/stacks/{stack_id}/stop"
    response = requests.post(url, headers=self.headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"停止Stack失败: {response.text}")
```

**改动说明**:
1. **删除容器创建方法**: 移除使用不存在API的方法
2. **新增Stack容器方法**: 通过Stack API部署单容器
3. **修复Stack创建**: 添加 `type=2` 参数
4. **修复Stack更新**: 添加 `Prune: false` 参数
5. **新增Stack管理**: 列表、详情、启动、停止方法

---

### 改动2: 优化 PortainerExecutor 部署逻辑

#### 文件位置
`backend/deploy_executors/portainer_executor.py`

#### 改动内容

**修改 `deploy_container` 方法**

```python
async def deploy_container(self, config: dict):
    """
    部署容器 - 改用 Stack API
    
    Args:
        config: 部署配置
    """
    client = self._get_portainer_client()
    
    # 提取配置
    container_name = config.get("container_name") or config.get("app_name")
    image = config["image"]
    ports = config.get("ports", [])
    env = config.get("env", [])
    volumes = config.get("volumes", [])
    restart_policy = config.get("restart_policy", "always")
    
    # ⚠️ 改用 Stack API 部署容器
    result = client.deploy_container_as_stack(
        container_name,
        image,
        ports=ports,
        env=env,
        volumes=volumes,
        restart_policy=restart_policy
    )
    
    return {
        "success": True,
        "message": f"容器 {container_name} 部署成功",
        "stack_id": result.get("Id"),
        "stack_name": container_name
    }
```

**改动说明**:
- Docker Run模式改用 `deploy_container_as_stack` 方法
- 通过创建单容器Stack实现容器部署

---

### 改动3: 新增 Stack 管理 API

#### 文件位置
`backend/routes.py`

#### 改动内容

**新增路由**

```python
@app.get("/api/agent-hosts/{host_id}/stacks")
async def get_portainer_stacks(host_id: int):
    """
    获取 Portainer 主机的 Stack 列表
    
    Args:
        host_id: 主机ID
    
    Returns:
        {
            "success": true,
            "stacks": [
                {
                    "id": 18,
                    "name": "my-app",
                    "status": 1,
                    "status_text": "运行中",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-16T15:20:00Z"
                }
            ]
        }
    """
    host = get_agent_host_by_id(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")
    
    if host.host_type != "portainer":
        raise HTTPException(status_code=400, detail="该主机不是 Portainer 类型")
    
    try:
        client = PortainerClient(
            host.portainer_url,
            host.portainer_api_key,
            host.portainer_endpoint_id
        )
        
        stacks = client.list_stacks()
        
        # 格式化返回数据
        formatted_stacks = []
        for stack in stacks:
            formatted_stacks.append({
                "id": stack["Id"],
                "name": stack["Name"],
                "status": stack["Status"],
                "status_text": "运行中" if stack["Status"] == 1 else "已停止",
                "created_at": stack.get("CreationDate"),
                "updated_at": stack.get("UpdateDate")
            })
        
        return {
            "success": True,
            "stacks": formatted_stacks
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }

@app.get("/api/agent-hosts/{host_id}/stacks/{stack_id}")
async def get_portainer_stack_details(host_id: int, stack_id: int):
    """
    获取 Stack 详情
    
    Args:
        host_id: 主机ID
        stack_id: Stack ID
    
    Returns:
        {
            "success": true,
            "stack": {
                "id": 18,
                "name": "my-app",
                "status": 1,
                "status_text": "运行中",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-16T15:20:00Z",
                "compose_content": "version: '3.8'..."
            }
        }
    """
    host = get_agent_host_by_id(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")
    
    if host.host_type != "portainer":
        raise HTTPException(status_code=400, detail="该主机不是 Portainer 类型")
    
    try:
        client = PortainerClient(
            host.portainer_url,
            host.portainer_api_key,
            host.portainer_endpoint_id
        )
        
        stack = client.get_stack(stack_id)
        
        return {
            "success": True,
            "stack": {
                "id": stack["Id"],
                "name": stack["Name"],
                "status": stack["Status"],
                "status_text": "运行中" if stack["Status"] == 1 else "已停止",
                "created_at": stack.get("CreationDate"),
                "updated_at": stack.get("UpdateDate"),
                "compose_content": stack.get("StackFileContent")
            }
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }
```

**改动说明**:
- 新增 `GET /api/agent-hosts/{host_id}/stacks` - 获取Stack列表
- 新增 `GET /api/agent-hosts/{host_id}/stacks/{stack_id}` - 获取Stack详情

---

## 三、改动影响范围

### 3.1 后端文件改动

| 文件 | 改动类型 | 影响范围 |
|------|----------|----------|
| `portainer_client.py` | 修改+新增 | 所有Portainer部署 |
| `portainer_executor.py` | 修改 | Docker Run部署 |
| `routes.py` | 新增 | Stack管理API |

### 3.2 API影响

| API | 改动类型 | 说明 |
|-----|----------|------|
| 容器创建 | ❌ 废弃 | 使用Stack方式替代 |
| Stack创建 | ✅ 修复 | 添加type=2参数 |
| Stack更新 | ✅ 修复 | 添加Prune参数 |
| Stack列表 | ✅ 新增 | 支持查询Stack列表 |
| Stack详情 | ✅ 新增 | 支持查询Stack配置 |

---

## 四、验收标准

### 4.1 API验收

- [ ] Docker Run模式通过Stack成功部署
- [ ] Stack创建包含 `type=2` 参数
- [ ] Stack更新包含 `Prune: false` 参数
- [ ] Stack列表API返回正确数据
- [ ] Stack详情API返回配置内容

### 4.2 功能验收

- [ ] 创建单容器Stack成功
- [ ] 更新已有Stack成功
- [ ] 查询Stack列表正常
- [ ] 查询Stack详情正常

---

## 五、测试建议

### 5.1 单元测试

```python
# 测试 Stack 创建
def test_deploy_stack_with_type_parameter():
    client = PortainerClient(...)
    result = client.deploy_stack("test-stack", compose_content)
    assert result["Id"] is not None

# 测试容器部署(通过Stack)
def test_deploy_container_as_stack():
    client = PortainerClient(...)
    result = client.deploy_container_as_stack(
        "nginx", 
        "nginx:latest",
        ports=[{"container_port": 80, "host_port": 8080}]
    )
    assert result["Id"] is not None
```

### 5.2 集成测试

```bash
# 测试 Stack 列表 API
curl -X GET http://localhost:8000/api/agent-hosts/1/stacks

# 测试 Stack 详情 API
curl -X GET http://localhost:8000/api/agent-hosts/1/stacks/18

# 测试 Docker Run 部署
curl -X POST http://localhost:8000/api/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "deploy_mode": "docker-run",
    "target_host_id": 1,
    "image": "nginx:latest",
    "container_name": "nginx-test"
  }'
```

---

## 六、回滚方案

如果出现问题,可以快速回滚:

```bash
# 后端回滚
git checkout HEAD -- backend/portainer_client.py
git checkout HEAD -- backend/deploy_executors/portainer_executor.py
git checkout HEAD -- backend/routes.py
```

---

## 七、关键代码位置总结

| 文件 | 改动位置 | 改动类型 |
|------|----------|----------|
| `portainer_client.py` | `deploy_container` 方法 | 删除 |
| `portainer_client.py` | `deploy_stack` 方法 | 修改(添加type参数) |
| `portainer_client.py` | `update_stack` 方法 | 修改(添加Prune参数) |
| `portainer_client.py` | 新增方法 | 新增Stack管理 |
| `portainer_executor.py` | `deploy_container` 方法 | 修改(改用Stack) |
| `routes.py` | 新增路由 | 新增Stack API |
