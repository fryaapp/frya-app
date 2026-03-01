package de.myfrya.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import de.myfrya.app.ui.AppRoot
import de.myfrya.app.ui.theme.FryaTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            FryaTheme {
                AppRoot()
            }
        }
    }
}
