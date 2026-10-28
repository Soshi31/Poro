package com.example.myapplication.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import com.example.myapplication.FreljordColors
import com.example.myapplication.FreljordShapes

@Composable
fun PoroAppTheme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = FreljordColors,
        shapes = FreljordShapes,
        content = content
    )
}
