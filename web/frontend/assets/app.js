const { createApp, ref, onMounted, reactive } = Vue;

createApp({
    setup() {
        const teachers = ref([]);
        const isEditing = ref(false);
        const isSaving = ref(false);
        const isUploading = ref(false);
        const isDragging = ref(false);
        const showSettings = ref(false);
        const downloadLink = ref(null);
        const toasts = ref([]);
        
        const initialForm = {
            id: null,
            short_name: '',
            full_name: '',
            position: '',
            rank: '',
            academic_degree: ''
        };

        const form = reactive({ ...initialForm });

        // Notifications
        const addToast = (title, message, type = 'info') => {
            toasts.value.push({ title, message, type });
            setTimeout(() => {
                removeToast(0);
            }, 5000);
        };

        const removeToast = (index) => {
            toasts.value.splice(index, 1);
        };

        // Fetch all teachers
        const fetchTeachers = async () => {
            try {
                const response = await axios.get('/api/teachers');
                teachers.value = response.data;
            } catch (error) {
                addToast('Ошибка', 'Не удалось загрузить список преподавателей', 'error');
                console.error(error);
            }
        };

        // Save teacher
        const saveTeacher = async () => {
            isSaving.value = true;
            try {
                if (isEditing.value) {
                    await axios.put(`/api/teachers/${form.id}`, form);
                    addToast('Успех', 'Данные преподавателя обновлены', 'success');
                } else {
                    await axios.post('/api/teachers', form);
                    addToast('Успех', 'Преподаватель добавлен', 'success');
                }
                resetForm();
                await fetchTeachers();
            } catch (error) {
                addToast('Ошибка', 'Не удалось сохранить данные', 'error');
                console.error(error);
            } finally {
                isSaving.value = false;
            }
        };

        const editTeacher = (teacher) => {
            isEditing.value = true;
            Object.assign(form, teacher);
            showSettings.value = true; // Open accordion automatically
        };

        const deleteTeacher = async (id) => {
            if (!confirm('Вы уверены, что хотите удалить этого преподавателя?')) return;
            
            try {
                await axios.delete(`/api/teachers/${id}`);
                addToast('Удалено', 'Преподаватель удален из базы', 'success');
                await fetchTeachers();
            } catch (error) {
                addToast('Ошибка', 'Не удалось удалить преподавателя', 'error');
            }
        };

        const resetForm = () => {
            isEditing.value = false;
            Object.assign(form, initialForm);
        };

        const resetDownload = () => {
            downloadLink.value = null;
        };

        // Upload Logic
        const uploadFiles = async (files) => {
            if (!files || files.length === 0) return;

            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            isUploading.value = true;
            downloadLink.value = null;

            try {
                const response = await axios.post('/api/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                
                if (response.data.status === 'success') {
                    downloadLink.value = `/api/download/${response.data.filename}`;
                    addToast('Готово', 'Расписание успешно сформировано', 'success');
                } else {
                    addToast('Внимание', response.data.message || 'Ошибка при обработке', 'info');
                }
            } catch (error) {
                addToast('Ошибка', 'Ошибка при загрузке или обработке файлов', 'error');
                console.error(error);
            } finally {
                isUploading.value = false;
                isDragging.value = false;
            }
        };

        const handleFileUpload = (event) => {
            uploadFiles(event.target.files);
        };

        // Drag and Drop handlers
        const onDragOver = () => {
            isDragging.value = true;
        };

        const onDragLeave = () => {
            isDragging.value = false;
        };

        const onDrop = (event) => {
            isDragging.value = false;
            const files = event.dataTransfer.files;
            uploadFiles(files);
        };

        onMounted(fetchTeachers);

        return {
            teachers, form, isEditing, isSaving, isUploading, isDragging,
            showSettings, downloadLink, toasts,
            saveTeacher, editTeacher, deleteTeacher, resetForm, resetDownload,
            handleFileUpload, onDragOver, onDragLeave, onDrop, removeToast
        };
    }
}).mount('#app');