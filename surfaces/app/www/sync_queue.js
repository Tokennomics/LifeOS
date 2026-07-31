/**
 * LifeOS PWA Offline Sync Queue Manager.
 *
 * Persists pending write operations to localStorage when network connectivity is lost
 * and replays queued transactions automatically once the connection is restored.
 */

(function () {
    const QUEUE_KEY = 'lifeos_offline_queue';

    function getQueue() {
        try {
            return JSON.parse(localStorage.getItem(QUEUE_KEY)) || [];
        } catch (e) {
            return [];
        }
    }

    function saveQueue(queue) {
        localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    }

    window.LifeOSSyncQueue = {
        /**
         * Queues a write transaction to replay later.
         */
        queueAction(endpoint, method = 'POST', payload = null) {
            const queue = getQueue();
            queue.push({
                id: Math.random().toString(36).substring(2, 9),
                endpoint,
                method,
                payload,
                timestamp: new Date().toISOString()
            });
            saveQueue(queue);
            console.log(`[SyncQueue] Action queued: ${method} ${endpoint}`);
        },

        /**
         * Replays all queued actions to the server.
         */
        async syncQueue(apiBaseUrl = '/v1') {
            if (!navigator.onLine) {
                console.log('[SyncQueue] Device is offline. Postponing sync.');
                return { status: 'offline', synced_count: 0 };
            }

            const queue = getQueue();
            if (queue.length === 0) {
                return { status: 'idle', synced_count: 0 };
            }

            console.log(`[SyncQueue] Starting sync for ${queue.length} action(s)...`);
            const remainingQueue = [];
            let syncedCount = 0;

            for (const action of queue) {
                try {
                    const res = await fetch(`${apiBaseUrl}${action.endpoint}`, {
                        method: action.method,
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: action.payload ? JSON.stringify(action.payload) : null
                    });

                    if (res.ok || res.status === 400 || res.status === 422) {
                        // Dequeue if transaction completed successfully or was invalid
                        syncedCount++;
                        console.log(`[SyncQueue] Successfully synced: ${action.method} ${action.endpoint}`);
                    } else {
                        // Keep in queue for retry if server error occurred (5xx or temporary network failure)
                        remainingQueue.push(action);
                    }
                } catch (err) {
                    console.error('[SyncQueue] Network error during action sync:', err);
                    remainingQueue.push(action);
                }
            }

            saveQueue(remainingQueue);
            return {
                status: 'sync_completed',
                synced_count: syncedCount,
                remaining_count: remainingQueue.length
            };
        },

        /**
         * Returns pending actions.
         */
        getPendingCount() {
            return getQueue().length;
        }
    };

    // Auto-sync listener when browser triggers transition to online state
    window.addEventListener('online', () => {
        console.log('[SyncQueue] Network connection detected. Initiating auto-sync.');
        window.LifeOSSyncQueue.syncQueue();
    });
})();
