// Common JavaScript utilities for B-Client Flask application

// API base URL
const API_BASE = window.location.origin;

// Utility functions
const Utils = {
    // Format time duration
    formatTime: function (seconds) {
        if (seconds < 60) {
            return `${seconds.toFixed(1)}s`;
        } else if (seconds < 3600) {
            return `${(seconds / 60).toFixed(1)}min`;
        } else {
            return `${(seconds / 3600).toFixed(1)}h`;
        }
    },

    // Format date for display
    formatDate: function (timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diffTime = Math.abs(now - date);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

        if (diffDays === 1) {
            return 'Today';
        } else if (diffDays === 2) {
            return 'Yesterday';
        } else if (diffDays <= 7) {
            return date.toLocaleDateString('en-US', { weekday: 'long' });
        } else {
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        }
    },

    // Escape HTML to prevent XSS
    escapeHtml: function (text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // Show notification
    showNotification: function (type, message) {
        // Remove existing notification if any
        const existingNotification = document.querySelector('.notification');
        if (existingNotification) {
            existingNotification.remove();
        }

        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;

        // Add styles
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            border-radius: 6px;
            color: white;
            font-weight: 600;
            z-index: 10000;
            max-width: 300px;
            word-wrap: break-word;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            transition: all 0.3s ease;
        `;

        // Set background color based on type
        if (type === 'success') {
            notification.style.background = '#4CAF50';
        } else if (type === 'error') {
            notification.style.background = '#f44336';
        } else {
            notification.style.background = '#2196F3';
        }

        // Add to page
        document.body.appendChild(notification);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.style.opacity = '0';
                notification.style.transform = 'translateX(100%)';
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.remove();
                    }
                }, 300);
            }
        }, 5000);

        // Allow manual close on click
        notification.onclick = () => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100%)';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 300);
        };
    }
};

// API functions
const API = {
    // Get dashboard stats
    getStats: async function () {
        try {
            const response = await fetch(`${API_BASE}/api/stats`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error fetching stats:', error);
            throw error;
        }
    },

    // Get configuration
    getConfig: async function () {
        try {
            const response = await fetch(`${API_BASE}/api/config`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error fetching config:', error);
            throw error;
        }
    },

    // Get cookies for a user
    getCookies: async function (userId) {
        try {
            const response = await fetch(`${API_BASE}/api/cookies?user_id=${userId}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error fetching cookies:', error);
            throw error;
        }
    },

    // Add or update cookie
    addCookie: async function (cookieData) {
        try {
            const response = await fetch(`${API_BASE}/api/cookies`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(cookieData)
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error adding cookie:', error);
            throw error;
        }
    },

    // Get accounts for a user
    getAccounts: async function (userId) {
        try {
            const response = await fetch(`${API_BASE}/api/accounts?user_id=${userId}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error fetching accounts:', error);
            throw error;
        }
    },

    // Add or update account
    addAccount: async function (accountData) {
        try {
            const response = await fetch(`${API_BASE}/api/accounts`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(accountData)
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error adding account:', error);
            throw error;
        }
    },

    // Delete account
    deleteAccount: async function (userId, username, website, account) {
        try {
            const response = await fetch(`${API_BASE}/api/accounts/${userId}/${username}/${website}/${account}`, {
                method: 'DELETE'
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('Error deleting account:', error);
            throw error;
        }
    }
};

// Export for use in other scripts
window.Utils = Utils;
window.API = API;
