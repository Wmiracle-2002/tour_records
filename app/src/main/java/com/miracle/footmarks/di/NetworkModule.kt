package com.miracle.footmarks.di

import com.miracle.footmarks.BuildConfig
import com.miracle.footmarks.data.remote.FootmarksApi
import com.miracle.footmarks.data.remote.PreferencesTokenStore
import com.miracle.footmarks.data.remote.TokenStore
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class TokenStoreModule {
    @Binds
    @Singleton
    abstract fun bindTokenStore(store: PreferencesTokenStore): TokenStore
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides
    @Singleton
    fun provideApi(): FootmarksApi = FootmarksApi.create(BuildConfig.FOOTMARKS_API_BASE_URL)
}
