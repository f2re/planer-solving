import { installWorkspaceMarkup, createWorkspaceState } from './workspace-state.js';
import { createScheduleState } from './schedule-state.js';

const { createApp, ref, onMounted } = Vue;

export function mount() {
    installWorkspaceMarkup();
    createApp({
        setup() {
            const toasts=ref([]);
            const addToast=(title,message,type='info')=>{const id=`${Date.now()}-${Math.random()}`;toasts.value.push({id,title,message,type});setTimeout(()=>toasts.value=toasts.value.filter(x=>x.id!==id),6500);};
            const removeToast=id=>toasts.value=toasts.value.filter(x=>x.id!==id);
            let schedule;
            const workspace=createWorkspaceState(addToast,()=>schedule?.invalidateAll());
            schedule=createScheduleState(addToast,workspace.activeWorkspaceId);

            const saveCurrentProfile=async()=>{
                const name=workspace.profileName.value.trim();
                if(!name||!schedule.currentLayout.value){addToast('Шаблон разметки','Введите название шаблона.','warning');return;}
                try{
                    const existing=workspace.layoutProfiles.value.find(x=>x.name.toLocaleLowerCase('ru')===name.toLocaleLowerCase('ru'));
                    const layout=schedule.normalizedLayout(schedule.currentLayout.value);
                    if(existing) await workspace.updateTemplateLayout(existing.id,layout,name,existing.description||'');
                    else await workspace.createTemplate(name,'',layout);
                    workspace.profileName.value=name;
                    addToast('Шаблон сохранён',`«${name}» сохранён в пространстве «${workspace.activeWorkspace.value?.name}».`,'success');
                }catch(e){addToast('Ошибка шаблона',e.response?.data?.detail||'Не удалось сохранить шаблон.','error');}
            };
            const applySelectedProfile=async()=>{if(workspace.selectedTemplate.value)await schedule.applyTemplate(workspace.selectedTemplate.value);};
            const deleteSelectedProfile=async()=>{if(workspace.selectedTemplate.value)await workspace.deleteTemplate(workspace.selectedTemplate.value);};
            const migrateLocalTemplates=async()=>{
                const key='planner-solving-layout-profiles-v1';
                if(workspace.layoutProfiles.value.length||localStorage.getItem(`${key}-migrated`))return;
                try{
                    const old=JSON.parse(localStorage.getItem(key)||'[]');
                    for(const item of Array.isArray(old)?old:[]) if(item?.name&&item?.layout) await workspace.createTemplate(item.name,'Перенесён из локального хранилища браузера',item.layout);
                    if(old.length)addToast('Шаблоны перенесены',`На сервер перенесено: ${old.length}.`,'success');
                    localStorage.setItem(`${key}-migrated`,'1');
                }catch(_){localStorage.setItem(`${key}-migrated`,'1');}
            };
            onMounted(async()=>{await workspace.init();await migrateLocalTemplates();});
            return {...workspace,...schedule,toasts,addToast,removeToast,saveCurrentProfile,applySelectedProfile,deleteSelectedProfile};
        }
    }).mount('#app');
}
