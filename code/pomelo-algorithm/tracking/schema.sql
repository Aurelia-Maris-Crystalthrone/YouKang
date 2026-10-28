-- 打药效果追踪模块 - MySQL 建表语句
-- 华为云 RDS 兼容，utf8mb4 编码
-- 用途：把一次性识别变成持续管理服务

USE pomelo_prescription;

-- ============================================================
-- 1. 观测记录表（observation）
-- ============================================================
-- 存储每次拍摄的图片及其检测结果，用于后续趋势分析
CREATE TABLE IF NOT EXISTS observation (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    orchard_id INT NOT NULL COMMENT '地块 ID（关联 orchard 表）',
    captured_at DATETIME NOT NULL COMMENT '拍摄时间',
    image_obs_path VARCHAR(500) COMMENT '图片 OBS 路径（如：obs://pomelo-agent/tracking/A1/20261028_143000.jpg）',
    gps_lat DECIMAL(10, 7) COMMENT 'GPS 纬度（可选）',
    gps_lng DECIMAL(10, 7) COMMENT 'GPS 经度（可选）',
    detection_result JSON COMMENT '检测结果 JSON：{ "detections": [{"label":"canker","confidence":0.85,"bbox":[x1,y1,x2,y2],"top2":[...]}], "is_healthy": false }',
    notes TEXT COMMENT '备注（如：人工补充观察）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (orchard_id) REFERENCES orchard(id) ON DELETE CASCADE,
    INDEX idx_orchard_time (orchard_id, captured_at),
    INDEX idx_captured_at (captured_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='观测记录表';

-- ============================================================
-- 2. 病情趋势表（disease_trend）
-- ============================================================
-- 存储每次比较的结果，避免重复计算
CREATE TABLE IF NOT EXISTS disease_trend (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    prev_observation_id INT NOT NULL COMMENT '前一次观测 ID',
    curr_observation_id INT NOT NULL COMMENT '本次观测 ID',
    conclusion ENUM('SPREADING', 'STABLE', 'RECOVERING') NOT NULL COMMENT '结论枚举',
    lesion_count_change INT COMMENT '病斑数量变化（正=增加，负=减少）',
    total_area_change DECIMAL(10, 4) COMMENT '总病斑面积变化率（正=扩大，负=缩小）',
    new_lesions JSON COMMENT '新增病斑位置 [{"x":..., "y":...}]',
    disappeared_lesions JSON COMMENT '消失病斑位置 [{"x":..., "y":...}]',
    recommendation TEXT COMMENT '基于趋势的建议（中文）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prev_observation_id) REFERENCES observation(id) ON DELETE CASCADE,
    FOREIGN KEY (curr_observation_id) REFERENCES observation(id) ON DELETE CASCADE,
    INDEX idx_conclusion (conclusion)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='病情趋势表';

-- ============================================================
-- 3. 病情曲线数据视图（用于鸿蒙 APP 渲染）
-- ============================================================
-- 注意：这是视图，不是表
CREATE OR REPLACE VIEW v_disease_curve AS
SELECT
    o.orchard_id,
    o.captured_at,
    o.detection_result,
    JSON_EXTRACT(o.detection_result, '$.detections') AS detections,
    dt.conclusion,
    dt.lesion_count_change,
    dt.total_area_change,
    dt.recommendation
FROM observation o
LEFT JOIN disease_trend dt ON o.id = dt.curr_observation_id
ORDER BY o.orchard_id, o.captured_at;

-- ============================================================
-- 4. 示例数据（可选）
-- ============================================================

-- 示例：A 区 1 号地块的两次观测
-- 第一次观测（2026-10-20）：检测到 3 个溃疡病斑
-- 第二次观测（2026-10-28）：检测到 5 个溃疡病斑，面积扩大
-- 结论：SPREADING（扩散）

-- 注意：实际数据由智能体调用 progress.py 后插入，此处仅作示例
-- INSERT INTO observation (orchard_id, captured_at, image_obs_path, detection_result) VALUES
-- (1, '2026-10-20 10:00:00', 'obs://pomelo-agent/tracking/A1/20261020_100000.jpg',
--  '{"detections":[{"label":"canker","confidence":0.85,"bbox":[100,100,150,150],"top2":[{"label":"canker","score":0.85},{"label":"anthracnose","score":0.42}]}],"is_healthy":false}');