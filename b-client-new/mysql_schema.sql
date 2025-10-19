-- =====================================================
-- B-Client MySQL Database Schema
-- 基于 models.py 生成的 MySQL 建表脚本
-- =====================================================

-- 创建数据库 (可选)
-- CREATE DATABASE IF NOT EXISTS b_client_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE b_client_db;

-- =====================================================
-- 1. user_cookies 表 - 用户Cookie管理
-- =====================================================
CREATE TABLE IF NOT EXISTS `user_cookies` (
    `user_id` VARCHAR(50) NOT NULL COMMENT 'User ID',
    `username` VARCHAR(255) NOT NULL COMMENT 'Username',
    `node_id` VARCHAR(50) DEFAULT NULL COMMENT 'Node ID where cookie was created',
    `cookie` TEXT DEFAULT NULL COMMENT 'Cookie content (encrypted)',
    `auto_refresh` BOOLEAN DEFAULT FALSE COMMENT 'Enable automatic cookie refresh',
    `refresh_time` DATETIME DEFAULT NULL COMMENT 'Last refresh timestamp',
    `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation time',
    
    PRIMARY KEY (`user_id`, `username`),
    INDEX `idx_node_id` (`node_id`),
    INDEX `idx_auto_refresh` (`auto_refresh`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User Cookie Management Table';

-- =====================================================
-- 2. user_accounts 表 - 用户账户管理
-- =====================================================
CREATE TABLE IF NOT EXISTS `user_accounts` (
    `user_id` VARCHAR(50) NOT NULL COMMENT 'User ID',
    `username` VARCHAR(255) NOT NULL COMMENT 'Username',
    `website` VARCHAR(255) NOT NULL COMMENT 'Website domain',
    `account` VARCHAR(50) NOT NULL COMMENT 'Account identifier',
    `password` TEXT DEFAULT NULL COMMENT 'Plain text password for login',
    `email` VARCHAR(255) DEFAULT NULL COMMENT 'Email address',
    `first_name` VARCHAR(255) DEFAULT NULL COMMENT 'First name',
    `last_name` VARCHAR(255) DEFAULT NULL COMMENT 'Last name',
    `location` VARCHAR(255) DEFAULT NULL COMMENT 'User location',
    `registration_method` VARCHAR(20) DEFAULT 'manual' COMMENT 'Registration method (manual/auto)',
    `auto_generated` BOOLEAN DEFAULT FALSE COMMENT 'Whether account was auto-generated',
    `logout` BOOLEAN DEFAULT FALSE COMMENT 'Whether user has logged out (prevents auto-login)',
    `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT 'Account creation time',
    
    PRIMARY KEY (`user_id`, `username`, `website`, `account`),
    INDEX `idx_website` (`website`),
    INDEX `idx_email` (`email`),
    INDEX `idx_registration_method` (`registration_method`),
    INDEX `idx_auto_generated` (`auto_generated`),
    INDEX `idx_logout` (`logout`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User Account Management Table';

-- =====================================================
-- 3. user_security_codes 表 - 用户安全码管理
-- =====================================================
CREATE TABLE IF NOT EXISTS `user_security_codes` (
    `nmp_user_id` VARCHAR(50) NOT NULL COMMENT 'NMP User ID (UUID)',
    `nmp_username` VARCHAR(50) NOT NULL COMMENT 'NMP Username',
    `domain_id` VARCHAR(50) DEFAULT NULL COMMENT 'Domain ID (UUID)',
    `cluster_id` VARCHAR(50) DEFAULT NULL COMMENT 'Cluster ID (UUID)',
    `channel_id` VARCHAR(50) DEFAULT NULL COMMENT 'Channel ID (UUID)',
    `security_code` VARCHAR(50) DEFAULT NULL COMMENT 'Security Code (UUID)',
    `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation time',
    `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update time',
    
    PRIMARY KEY (`nmp_user_id`),
    UNIQUE KEY `uk_nmp_username` (`nmp_username`),
    INDEX `idx_domain_id` (`domain_id`),
    INDEX `idx_cluster_id` (`cluster_id`),
    INDEX `idx_channel_id` (`channel_id`),
    INDEX `idx_security_code` (`security_code`),
    INDEX `idx_create_time` (`create_time`),
    INDEX `idx_update_time` (`update_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User Security Code Table';

-- =====================================================
-- 4. 可选：添加外键约束 (如果需要)
-- =====================================================
-- 注意：由于使用了复合主键，外键约束可能比较复杂
-- 以下是一些可能的外键关系示例：

-- ALTER TABLE `user_cookies` 
-- ADD CONSTRAINT `fk_user_cookies_user_accounts` 
-- FOREIGN KEY (`user_id`, `username`) 
-- REFERENCES `user_accounts`(`user_id`, `username`) 
-- ON DELETE CASCADE ON UPDATE CASCADE;

-- =====================================================
-- 5. 创建视图 (可选) - 便于查询
-- =====================================================

-- 用户完整信息视图
CREATE OR REPLACE VIEW `v_user_complete_info` AS
SELECT 
    ua.user_id,
    ua.username,
    ua.website,
    ua.account,
    ua.email,
    ua.first_name,
    ua.last_name,
    ua.location,
    ua.registration_method,
    ua.auto_generated,
    ua.logout,
    ua.create_time as account_create_time,
    uc.node_id,
    uc.auto_refresh,
    uc.refresh_time,
    uc.create_time as cookie_create_time,
    usc.domain_id,
    usc.cluster_id,
    usc.channel_id,
    usc.security_code,
    usc.update_time as security_code_update_time
FROM `user_accounts` ua
LEFT JOIN `user_cookies` uc ON ua.user_id = uc.user_id AND ua.username = uc.username
LEFT JOIN `user_security_codes` usc ON ua.user_id = usc.nmp_user_id;

-- 活跃用户统计视图
CREATE OR REPLACE VIEW `v_active_users_stats` AS
SELECT 
    COUNT(DISTINCT ua.user_id) as total_users,
    COUNT(DISTINCT CASE WHEN ua.logout = FALSE THEN ua.user_id END) as active_users,
    COUNT(DISTINCT CASE WHEN ua.auto_generated = TRUE THEN ua.user_id END) as auto_generated_users,
    COUNT(DISTINCT ua.website) as total_websites,
    COUNT(DISTINCT uc.user_id) as users_with_cookies,
    COUNT(DISTINCT usc.nmp_user_id) as users_with_security_codes
FROM `user_accounts` ua
LEFT JOIN `user_cookies` uc ON ua.user_id = uc.user_id AND ua.username = uc.username
LEFT JOIN `user_security_codes` usc ON ua.user_id = usc.nmp_user_id;

-- =====================================================
-- 6. 创建存储过程 (可选) - 常用操作
-- =====================================================

DELIMITER //

-- 清理过期Cookie的存储过程
CREATE PROCEDURE `sp_cleanup_expired_cookies`(IN days_old INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;
    
    START TRANSACTION;
    
    DELETE FROM `user_cookies` 
    WHERE `refresh_time` IS NOT NULL 
    AND `refresh_time` < DATE_SUB(NOW(), INTERVAL days_old DAY);
    
    COMMIT;
END //

-- 获取用户统计信息的存储过程
CREATE PROCEDURE `sp_get_user_stats`()
BEGIN
    SELECT 
        (SELECT COUNT(*) FROM `user_accounts`) as total_accounts,
        (SELECT COUNT(*) FROM `user_cookies`) as total_cookies,
        (SELECT COUNT(*) FROM `user_security_codes`) as total_security_codes,
        (SELECT COUNT(DISTINCT user_id) FROM `user_accounts`) as unique_users,
        (SELECT COUNT(DISTINCT website) FROM `user_accounts`) as unique_websites;
END //

DELIMITER ;

-- =====================================================
-- 7. 创建触发器 (可选) - 自动维护
-- =====================================================

-- 用户账户创建时自动创建安全码记录
DELIMITER //
CREATE TRIGGER `tr_user_account_after_insert` 
AFTER INSERT ON `user_accounts`
FOR EACH ROW
BEGIN
    -- 如果安全码表中不存在该用户，则插入一条记录
    INSERT IGNORE INTO `user_security_codes` 
    (`nmp_user_id`, `nmp_username`, `create_time`, `update_time`)
    VALUES (NEW.user_id, NEW.username, NOW(), NOW());
END //
DELIMITER ;

-- =====================================================
-- 8. 插入示例数据 (可选)
-- =====================================================

-- 插入示例用户账户
INSERT INTO `user_accounts` 
(`user_id`, `username`, `website`, `account`, `email`, `first_name`, `last_name`, `registration_method`, `auto_generated`) 
VALUES 
('user-001', 'testuser', 'example.com', 'main', 'test@example.com', 'Test', 'User', 'manual', FALSE),
('user-002', 'autouser', 'demo.com', 'auto', 'auto@demo.com', 'Auto', 'User', 'auto', TRUE);

-- 插入示例Cookie
INSERT INTO `user_cookies` 
(`user_id`, `username`, `node_id`, `cookie`, `auto_refresh`) 
VALUES 
('user-001', 'testuser', 'node-001', 'encrypted_cookie_data_here', TRUE),
('user-002', 'autouser', 'node-002', 'encrypted_cookie_data_here', FALSE);

-- 插入示例安全码
INSERT INTO `user_security_codes` 
(`nmp_user_id`, `nmp_username`, `domain_id`, `cluster_id`, `channel_id`, `security_code`) 
VALUES 
('user-001', 'testuser', 'domain-001', 'cluster-001', 'channel-001', 'security-code-001'),
('user-002', 'autouser', 'domain-002', 'cluster-002', 'channel-002', 'security-code-002');

-- =====================================================
-- 脚本执行完成
-- =====================================================
