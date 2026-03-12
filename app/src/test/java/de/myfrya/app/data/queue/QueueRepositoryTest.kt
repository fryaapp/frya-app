package de.myfrya.app.data.queue

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29])
class QueueRepositoryTest {

    private lateinit var db: AppDatabase
    private lateinit var dao: QueueDao
    private lateinit var repository: QueueRepository

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        WorkManagerTestInitHelper.initializeTestWorkManager(context)
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        dao = db.queueDao()
        repository = QueueRepository(dao, context)
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun enqueueFakeItem_createsOneEntryWithStatusPending() = runTest {
        repository.enqueueFakeItem()
        val list = repository.observeQueue().first()
        assertEquals(1, list.size)
        assertEquals("PENDING", list[0].status)
        assertEquals("local://dummy", list[0].filePath)
    }

    @Test
    fun retryFailed_setsFailedToPendingAndClearsErrorMessage() = runTest {
        val t = System.currentTimeMillis()
        dao.insert(QueueItemEntity(createdAt = t, filePath = "f", pageCount = 1, status = "FAILED", errorMessage = "err"))
        repository.retryFailed()
        val list = repository.observeQueue().first()
        assertEquals(1, list.size)
        assertEquals("PENDING", list[0].status)
        assertNull(list[0].errorMessage)
    }
}
