package de.myfrya.app.data.queue

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29])
class QueueDaoTest {

    private lateinit var db: AppDatabase
    private lateinit var dao: QueueDao

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        dao = db.queueDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun getOldestPending_returnsOldestPendingWhenMultiplePendingAndFailed() = runTest {
        val t = System.currentTimeMillis()
        dao.insert(QueueItemEntity(createdAt = t, filePath = "first", pageCount = 1, status = "PENDING"))
        dao.insert(QueueItemEntity(createdAt = t + 1, filePath = "second", pageCount = 1, status = "PENDING"))
        dao.insert(QueueItemEntity(createdAt = t + 2, filePath = "failed", pageCount = 1, status = "FAILED"))
        val oldest = dao.getOldestPending()
        assertNotNull(oldest)
        assertEquals("PENDING", requireNotNull(oldest).status)
        assertEquals("first", oldest.filePath)
    }

    @Test
    fun getOldestPending_returnsNullWhenNoPending() = runTest {
        val t = System.currentTimeMillis()
        dao.insert(QueueItemEntity(createdAt = t, filePath = "a", pageCount = 1, status = "SUCCESS"))
        val oldest = dao.getOldestPending()
        assertNull(oldest)
    }

    @Test
    fun updateStatus_toSuccess_isVisibleInObserveAll() = runTest {
        val t = System.currentTimeMillis()
        val id = dao.insert(QueueItemEntity(createdAt = t, filePath = "x", pageCount = 1, status = "PENDING"))
        dao.updateStatus(id, "SUCCESS", null)
        val list = dao.observeAll().first()
        assertEquals(1, list.size)
        assertEquals("SUCCESS", list[0].status)
    }
}
