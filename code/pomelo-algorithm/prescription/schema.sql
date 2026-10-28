-- 农药数据库与规则引擎 - MySQL 建表语句
-- 华为云 RDS 兼容，utf8mb4 编码
-- 创建数据库：CREATE DATABASE pomelo_prescription CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE pomelo_prescription;

-- 1. 农药主表
CREATE TABLE IF NOT EXISTS pesticide (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    common_name VARCHAR(100) NOT NULL UNIQUE COMMENT '通用名（中文）',
    trade_names TEXT COMMENT '商品名示例（JSON 数组或逗号分隔）',
    active_ingredient VARCHAR(200) NOT NULL COMMENT '有效成分',
    formulation VARCHAR(50) COMMENT '剂型（如：乳油、悬浮剂、水分散粒剂）',
    content VARCHAR(100) COMMENT '含量（如：1.8% 乳油、240g/L 悬浮剂）',
    frac_irac_code VARCHAR(50) COMMENT '作用机理分组码（FRAC 码杀菌剂、IRAC 码杀虫剂）',
    phi_days INT COMMENT '安全间隔期 PHI（天），距采收最少天数',
    max_times_per_season INT COMMENT '每季最多使用次数',
    registered_crops TEXT COMMENT '登记作物（JSON 数组，如 ["柑橘","苹果"]）',
    toxicity_level VARCHAR(30) COMMENT '毒性等级（微毒/低毒/中等毒/高毒/剧毒）',
    is_banned TINYINT(1) DEFAULT 0 COMMENT '是否禁用（1=禁用，0=可用）',
    data_source VARCHAR(200) COMMENT '数据来源（如：《农药登记公告》《柑橘病虫害防治手册》）',
    notes TEXT COMMENT '备注（需植保专家核实的内容）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_phi (phi_days),
    INDEX idx_banned (is_banned),
    INDEX idx_toxicity (toxicity_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='农药主表';

-- 2. 病害-药剂关联表
CREATE TABLE IF NOT EXISTS pest_pesticide (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    pest_name VARCHAR(100) NOT NULL COMMENT '病害名（与 labelmap 的 label 对应：red_spider_mite/anthracnose/canker/greening）',
    pesticide_id INT NOT NULL COMMENT '农药 ID',
    is_registered_for_citrus TINYINT(1) DEFAULT 1 COMMENT '是否在柑橘类登记（1=是，0=否）',
    dilution_ratio VARCHAR(50) COMMENT '推荐稀释倍数（如：3000 倍液）',
    application_method VARCHAR(100) COMMENT '施用方法（如：喷施叶背、全株喷雾）',
    application_timing VARCHAR(100) COMMENT '施用时机（如：萌芽前、幼果期、采后清园）',
    data_source VARCHAR(200) COMMENT '数据来源',
    notes TEXT COMMENT '备注',
    FOREIGN KEY (pesticide_id) REFERENCES pesticide(id) ON DELETE CASCADE,
    UNIQUE KEY uk_pest_pesticide (pest_name, pesticide_id),
    INDEX idx_pest (pest_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='病害-药剂关联表';

-- 3. 地块表
CREATE TABLE IF NOT EXISTS orchard (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    block_name VARCHAR(100) NOT NULL UNIQUE COMMENT '地块名称',
    variety VARCHAR(100) COMMENT '品种（如：琯溪蜜柚、红肉蜜柚、沙田柚）',
    tree_age INT COMMENT '树龄（年）',
    current_phenophase VARCHAR(50) COMMENT '当前物候期（萌芽期/花期/幼果期/膨大期/转色期/采收期/休眠期）',
    expected_harvest_date DATE COMMENT '预计采收日期',
    area_mu DECIMAL(10,2) COMMENT '面积（亩）',
    location VARCHAR(200) COMMENT '地理位置',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_phenophase (current_phenophase),
    INDEX idx_harvest (expected_harvest_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='地块表';

-- 4. 施药记录表
CREATE TABLE IF NOT EXISTS spray_record (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    orchard_id INT NOT NULL COMMENT '地块 ID',
    spray_date DATE NOT NULL COMMENT '施药日期',
    pesticide_id INT NOT NULL COMMENT '农药 ID',
    dilution_ratio VARCHAR(50) COMMENT '实际稀释倍数',
    dosage_per_mu DECIMAL(10,2) COMMENT '用量（克/亩 或 毫升/亩）',
    sprayed_by VARCHAR(100) COMMENT '施药人',
    notes TEXT COMMENT '备注',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (orchard_id) REFERENCES orchard(id) ON DELETE CASCADE,
    FOREIGN KEY (pesticide_id) REFERENCES pesticide(id) ON DELETE CASCADE,
    INDEX idx_orchard_date (orchard_id, spray_date),
    INDEX idx_date (spray_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='施药记录表';

-- 5. 配伍禁忌表
CREATE TABLE IF NOT EXISTS pesticide_conflict (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    pesticide_a_id INT NOT NULL COMMENT '药剂 A ID',
    pesticide_b_id INT NOT NULL COMMENT '药剂 B ID',
    conflict_type VARCHAR(50) NOT NULL COMMENT '禁忌类型（药害/药效降低/毒性增强/沉淀失效/未知）',
    description TEXT COMMENT '禁忌说明（中文）',
    severity VARCHAR(20) DEFAULT '中等' COMMENT '严重程度（轻微/中等/严重/致命）',
    data_source VARCHAR(200) COMMENT '数据来源',
    notes TEXT COMMENT '备注',
    FOREIGN KEY (pesticide_a_id) REFERENCES pesticide(id) ON DELETE CASCADE,
    FOREIGN KEY (pesticide_b_id) REFERENCES pesticide(id) ON DELETE CASCADE,
    UNIQUE KEY uk_pair (pesticide_a_id, pesticide_b_id),
    INDEX idx_type (conflict_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='配伍禁忌表';

-- 6. 物候期禁忌表（补充表，记录哪些药剂在哪些物候期禁用）
CREATE TABLE IF NOT EXISTS phenophase_contraindication (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键 ID',
    pesticide_id INT NOT NULL COMMENT '农药 ID',
    phenophase VARCHAR(50) NOT NULL COMMENT '禁用物候期（花期/幼果期/转色期等）',
    reason TEXT COMMENT '禁用原因',
    data_source VARCHAR(200) COMMENT '数据来源',
    FOREIGN KEY (pesticide_id) REFERENCES pesticide(id) ON DELETE CASCADE,
    UNIQUE KEY uk_pesticide_phenophase (pesticide_id, phenophase)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='物候期禁忌表';